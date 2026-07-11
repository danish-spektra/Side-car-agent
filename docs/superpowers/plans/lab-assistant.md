# CloudLabs Lab Assistant Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Grounded Q&A sidecar for CloudLabs learners — a thin in-VM Go agent that asks a central FastAPI orchestrator questions answered from the lab's own (vision-enriched) guide plus MS Learn.

**Architecture:** Central FastAPI orchestrator (instructor portal + ingest pipeline + query API + metering) deployed via `azd` to the instructor's MSDN sub. Ingest is masterdoc-driven: fetch markdown in `Order` via the CloudLabs docs-api proxy, resolve each image's *relative* path against its markdown file's URL, vision-caption once, store one enriched guide per `eventID` (no vector DB — full-context stuffing). Per-VM Go sidecar serves a local chat UI on `127.0.0.1:7788` and proxies to the orchestrator with `eventID` + scoped key.

**Tech Stack:** Python 3.14 / FastAPI / httpx / openai SDK / azure-storage-blob / pytest; Go 1.22 (stdlib only); Bicep + azd; PowerShell for VM install.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-03-sidecar-agent-design.md`.
- **No Azure AI Search.** Guide is context-stuffed whole.
- Vision captioning happens **only at ingest**, never at query time.
- The agent **explains and points — never performs lab steps** (system prompt, Task 9).
- Isolation: every query is scoped by `eventID` + per-event key; wrong key → 401.
- Metering: one append-only line per query: `eventID, deploymentID, ts, tokens_in, tokens_out`.
- Chat model deployment name is config (`AZURE_OPENAI_CHAT_DEPLOYMENT`), default `gpt-4o`; pin latest GA GPT-5.x at `azd up` time via Bicep param.
- All Python code is **sync** (no asyncio) — smaller test surface.
- `<inject key="..."/>` tokens are per-learner placeholders — the model must explain them, not read them literally.
- Repo layout: `orchestrator/` (Python), `sidecar/` (Go), `infra/` (Bicep + azure.yaml at repo root), `scripts/` (PowerShell + ARM snippets).
- Commit after every task (steps include it).

## File Structure

```
orchestrator/
  app/__init__.py
  app/config.py          # env settings
  app/storage.py         # Storage protocol + Local/Blob backends + event records
  app/ingest.py          # masterdoc parse, image resolve, enrich pipeline
  app/captioner.py       # vision captions (injectable OpenAI client)
  app/mslearn.py         # MS Learn search client
  app/metering.py        # append-only usage log
  app/main.py            # FastAPI app: events, ingest, query, portal, sidecar.zip
  app/portal/index.html  # instructor single page
  static/                # sidecar.zip dropped here by build script
  tests/                 # pytest
  requirements.txt
sidecar/
  main.go                # config load + local server + proxy
  ui/index.html          # learner chat page (embedded)
  main_test.go
  build.ps1              # builds exe, zips with README into orchestrator/static/
infra/
  main.bicep             # App Service + Azure OpenAI + Storage
  main.parameters.json
azure.yaml               # azd service map (repo root)
scripts/
  InstallSidecarAgent.ps1   # function to merge into cloudlabs-windows-functions.ps1
  arm-snippet.md            # params + commandToExecute wiring for deploy.json
  demo-integration.md       # the one line for demo.ps1
  local_lab_server.py       # serves reference-guide/ + generated local masterdoc for E2E
```

---

### Task 1: Orchestrator scaffold (FastAPI + config + healthz)

**Files:**
- Create: `orchestrator/requirements.txt`, `orchestrator/app/__init__.py`, `orchestrator/app/config.py`, `orchestrator/app/main.py`, `orchestrator/tests/test_health.py`

**Interfaces:**
- Produces: `app.config.Settings` (env-driven), `app.main.app` (FastAPI), `get_settings()` cached accessor.

- [ ] **Step 1: Write the failing test**

`orchestrator/tests/test_health.py`:
```python
from fastapi.testclient import TestClient
from app.main import app

def test_healthz():
    client = TestClient(app)
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `orchestrator/`): `python -m pytest tests/test_health.py -v`
Expected: FAIL / ImportError (`app.main` missing).

- [ ] **Step 3: Write minimal implementation**

`orchestrator/requirements.txt`:
```
fastapi
uvicorn[standard]
pydantic-settings
httpx
openai
azure-storage-blob
python-multipart
pytest
```

`orchestrator/app/__init__.py`: empty file.

`orchestrator/app/config.py`:
```python
from functools import lru_cache
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_chat_deployment: str = "gpt-4o"
    storage_backend: str = "local"          # "local" | "blob"
    data_dir: str = "./data"
    azure_storage_connection_string: str = ""

@lru_cache
def get_settings() -> Settings:
    return Settings()
```

`orchestrator/app/main.py`:
```python
from fastapi import FastAPI

app = FastAPI(title="CloudLabs Lab Assistant Orchestrator")

@app.get("/healthz")
def healthz():
    return {"status": "ok"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pip install -r requirements.txt && python -m pytest tests/ -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add orchestrator/
git commit -m "feat: orchestrator scaffold with healthz"
```

---

### Task 2: Storage backends + event records

**Files:**
- Create: `orchestrator/app/storage.py`, `orchestrator/tests/test_storage.py`

**Interfaces:**
- Produces:
  - `Storage` protocol: `save_text(event_id, name, text)`, `load_text(event_id, name) -> str` (raises `KeyError` if missing), `exists(event_id, name) -> bool`, `append_line(event_id, name, line)`
  - `LocalStorage(data_dir)`, `BlobStorage(connection_string)` (container `events`, blob `{event_id}/{name}`)
  - `get_storage(settings) -> Storage`
  - `create_event(storage, name) -> dict` returns `{"event_id","key","name","status"}` and persists `event.json`
  - `get_event(storage, event_id) -> dict | None`
  - `verify_key(storage, event_id, key) -> bool`

- [ ] **Step 1: Write the failing tests**

`orchestrator/tests/test_storage.py`:
```python
import pytest
from app.storage import LocalStorage, create_event, get_event, verify_key

@pytest.fixture
def storage(tmp_path):
    return LocalStorage(str(tmp_path))

def test_save_load_roundtrip(storage):
    storage.save_text("ev1", "guide.md", "# hello")
    assert storage.load_text("ev1", "guide.md") == "# hello"
    assert storage.exists("ev1", "guide.md")
    assert not storage.exists("ev1", "nope.md")

def test_load_missing_raises(storage):
    with pytest.raises(KeyError):
        storage.load_text("ev1", "missing.md")

def test_append_line(storage):
    storage.append_line("ev1", "usage.jsonl", '{"a":1}')
    storage.append_line("ev1", "usage.jsonl", '{"a":2}')
    assert storage.load_text("ev1", "usage.jsonl").splitlines() == ['{"a":1}', '{"a":2}']

def test_event_lifecycle(storage):
    ev = create_event(storage, "AI Foundry Workshop")
    assert ev["name"] == "AI Foundry Workshop"
    assert len(ev["key"]) >= 32
    fetched = get_event(storage, ev["event_id"])
    assert fetched["key"] == ev["key"]
    assert verify_key(storage, ev["event_id"], ev["key"])
    assert not verify_key(storage, ev["event_id"], "wrong")
    assert not verify_key(storage, "missing", ev["key"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_storage.py -v` → FAIL (module missing).

- [ ] **Step 3: Implement**

`orchestrator/app/storage.py`:
```python
import json
import secrets
import uuid
from pathlib import Path
from typing import Protocol

class Storage(Protocol):
    def save_text(self, event_id: str, name: str, text: str) -> None: ...
    def load_text(self, event_id: str, name: str) -> str: ...
    def exists(self, event_id: str, name: str) -> bool: ...
    def append_line(self, event_id: str, name: str, line: str) -> None: ...

class LocalStorage:
    def __init__(self, data_dir: str):
        self.root = Path(data_dir)

    def _path(self, event_id: str, name: str) -> Path:
        p = self.root / event_id / name
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def save_text(self, event_id, name, text):
        self._path(event_id, name).write_text(text, encoding="utf-8")

    def load_text(self, event_id, name):
        p = self._path(event_id, name)
        if not p.exists():
            raise KeyError(f"{event_id}/{name}")
        return p.read_text(encoding="utf-8")

    def exists(self, event_id, name):
        return self._path(event_id, name).exists()

    def append_line(self, event_id, name, line):
        with self._path(event_id, name).open("a", encoding="utf-8") as f:
            f.write(line + "\n")

class BlobStorage:
    """Same contract on Azure Blob. Container 'events', blob '{event_id}/{name}'."""
    def __init__(self, connection_string: str):
        from azure.storage.blob import BlobServiceClient
        svc = BlobServiceClient.from_connection_string(connection_string)
        self.container = svc.get_container_client("events")
        try:
            self.container.create_container()
        except Exception:
            pass  # already exists

    def _blob(self, event_id, name):
        return self.container.get_blob_client(f"{event_id}/{name}")

    def save_text(self, event_id, name, text):
        self._blob(event_id, name).upload_blob(text.encode("utf-8"), overwrite=True)

    def load_text(self, event_id, name):
        from azure.core.exceptions import ResourceNotFoundError
        try:
            return self._blob(event_id, name).download_blob().readall().decode("utf-8")
        except ResourceNotFoundError:
            raise KeyError(f"{event_id}/{name}")

    def exists(self, event_id, name):
        return self._blob(event_id, name).exists()

    def append_line(self, event_id, name, line):
        # ponytail: read-modify-write append; AppendBlob if metering volume ever matters
        try:
            current = self.load_text(event_id, name)
        except KeyError:
            current = ""
        self.save_text(event_id, name, current + line + "\n")

def get_storage(settings) -> Storage:
    if settings.storage_backend == "blob":
        return BlobStorage(settings.azure_storage_connection_string)
    return LocalStorage(settings.data_dir)

# ---- event records ----

def create_event(storage: Storage, name: str) -> dict:
    event = {
        "event_id": uuid.uuid4().hex[:12],
        "key": secrets.token_urlsafe(32),
        "name": name,
        "status": "created",
    }
    storage.save_text(event["event_id"], "event.json", json.dumps(event))
    return event

def get_event(storage: Storage, event_id: str) -> dict | None:
    try:
        return json.loads(storage.load_text(event_id, "event.json"))
    except KeyError:
        return None

def verify_key(storage: Storage, event_id: str, key: str) -> bool:
    ev = get_event(storage, event_id)
    return bool(ev) and secrets.compare_digest(ev["key"], key)
```

- [ ] **Step 4: Run tests** → `python -m pytest tests/test_storage.py -v` → PASS (BlobStorage is exercised in Azure, not unit tests).

- [ ] **Step 5: Commit**

```bash
git add orchestrator/app/storage.py orchestrator/tests/test_storage.py
git commit -m "feat: storage backends and event records"
```

---

### Task 3: Masterdoc parsing + ordered fetch + image resolution

**Files:**
- Create: `orchestrator/app/ingest.py` (first half), `orchestrator/tests/test_ingest.py`

**Interfaces:**
- Produces (in `app.ingest`):
  - `ordered_paths(masterdoc: list | dict) -> list[str]` — RawFilePaths sorted by `Order`
  - `extract_image_refs(md: str) -> list[str]`
  - `resolve_ref(md_url: str, ref: str) -> str` — urljoin; absolute refs pass through
  - `http_fetch(url: str) -> bytes` — httpx GET, `raise_for_status`, 30s timeout
- Consumes: nothing prior.

- [ ] **Step 1: Write the failing tests**

`orchestrator/tests/test_ingest.py`:
```python
from app.ingest import ordered_paths, extract_image_refs, resolve_ref

MASTERDOC = [{
    "Name": "Demo",
    "Files": [
        {"RawFilePath": "https://x/Labs/Exercise-1.md", "Order": 2},
        {"RawFilePath": "https://x/Labs/gettingstarted.md", "Order": 1},
    ],
}]

def test_ordered_paths_sorts_by_order():
    assert ordered_paths(MASTERDOC) == [
        "https://x/Labs/gettingstarted.md",
        "https://x/Labs/Exercise-1.md",
    ]

def test_ordered_paths_accepts_single_object():
    assert ordered_paths(MASTERDOC[0])[0] == "https://x/Labs/gettingstarted.md"

def test_extract_image_refs():
    md = "text\n![](../images/a.png)\nmore ![alt](https://cdn/b.jpg) end"
    assert extract_image_refs(md) == ["../images/a.png", "https://cdn/b.jpg"]

def test_resolve_ref_relative():
    assert (
        resolve_ref("https://docs-api.cloudlabs.ai/repos/raw.githubusercontent.com/O/R/refs/heads/main/Labs/Exercise-1.md",
                    "../images/aisnew.png")
        == "https://docs-api.cloudlabs.ai/repos/raw.githubusercontent.com/O/R/refs/heads/main/images/aisnew.png"
    )

def test_resolve_ref_absolute_passthrough():
    assert resolve_ref("https://x/Labs/e.md", "https://cdn/b.jpg") == "https://cdn/b.jpg"
```

- [ ] **Step 2: Run tests** → FAIL (module missing).

- [ ] **Step 3: Implement**

`orchestrator/app/ingest.py`:
```python
import re
from urllib.parse import urljoin

import httpx

IMG_RE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")

def ordered_paths(masterdoc) -> list[str]:
    doc = masterdoc[0] if isinstance(masterdoc, list) else masterdoc
    files = sorted(doc["Files"], key=lambda f: f["Order"])
    return [f["RawFilePath"] for f in files]

def extract_image_refs(md: str) -> list[str]:
    return IMG_RE.findall(md)

def resolve_ref(md_url: str, ref: str) -> str:
    return ref if ref.startswith(("http://", "https://")) else urljoin(md_url, ref)

def http_fetch(url: str) -> bytes:
    r = httpx.get(url, timeout=30, follow_redirects=True)
    r.raise_for_status()
    return r.content
```

- [ ] **Step 4: Run tests** → PASS.

- [ ] **Step 5: Commit**

```bash
git add orchestrator/app/ingest.py orchestrator/tests/test_ingest.py
git commit -m "feat: masterdoc parsing and dynamic image resolution"
```

---

### Task 4: Vision captioner

**Files:**
- Create: `orchestrator/app/captioner.py`, `orchestrator/tests/test_captioner.py`

**Interfaces:**
- Produces: `Captioner(client, deployment)` with `caption(image_bytes: bytes, mime: str = "image/png") -> str`. `client` is an `openai.AzureOpenAI`-compatible object (injectable fake in tests). `make_openai_client(settings)` factory.
- Consumes: `Settings` from Task 1.

- [ ] **Step 1: Write the failing test**

`orchestrator/tests/test_captioner.py`:
```python
import base64
from app.captioner import Captioner

class FakeCompletions:
    def __init__(self):
        self.last_kwargs = None
    def create(self, **kwargs):
        self.last_kwargs = kwargs
        class Msg: content = "Azure portal search bar with AI Search typed."
        class Choice: message = Msg()
        class Resp: choices = [Choice()]
        return Resp()

class FakeClient:
    def __init__(self):
        self.chat = type("C", (), {"completions": FakeCompletions()})()

def test_caption_sends_data_url_and_returns_text():
    client = FakeClient()
    cap = Captioner(client, "gpt-4o")
    out = cap.caption(b"\x89PNG fake", mime="image/png")
    assert out == "Azure portal search bar with AI Search typed."
    kwargs = client.chat.completions.create.__self__.last_kwargs
    assert kwargs["model"] == "gpt-4o"
    image_part = kwargs["messages"][0]["content"][1]
    assert image_part["type"] == "image_url"
    expected_b64 = base64.b64encode(b"\x89PNG fake").decode()
    assert image_part["image_url"]["url"] == f"data:image/png;base64,{expected_b64}"
```

- [ ] **Step 2: Run test** → FAIL.

- [ ] **Step 3: Implement**

`orchestrator/app/captioner.py`:
```python
import base64

CAPTION_PROMPT = (
    "Describe this lab-guide screenshot in 1-3 sentences for a learner who "
    "cannot see it: name the screen or portal blade, the highlighted/numbered "
    "UI elements, and where they are located on the screen."
)

class Captioner:
    def __init__(self, client, deployment: str):
        self.client = client
        self.deployment = deployment

    def caption(self, image_bytes: bytes, mime: str = "image/png") -> str:
        data_url = f"data:{mime};base64,{base64.b64encode(image_bytes).decode()}"
        resp = self.client.chat.completions.create(
            model=self.deployment,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": CAPTION_PROMPT},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }],
            max_tokens=150,
        )
        return resp.choices[0].message.content.strip()

def make_openai_client(settings):
    from openai import AzureOpenAI
    return AzureOpenAI(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        api_version="2024-06-01",
    )
```

- [ ] **Step 4: Run test** → PASS.

- [ ] **Step 5: Commit**

```bash
git add orchestrator/app/captioner.py orchestrator/tests/test_captioner.py
git commit -m "feat: vision captioner with injectable client"
```

---

### Task 5: Enrichment pipeline (`ingest_event`)

**Files:**
- Modify: `orchestrator/app/ingest.py` (append), `orchestrator/tests/test_ingest.py` (append)

**Interfaces:**
- Produces (in `app.ingest`):
  - `enrich_markdown(md, base_url, fetch, caption_fn, cache) -> str` — after each image ref, inserts `> [Screenshot] {caption}` and `> (image: {resolved_url})` lines
  - `ingest_event(storage, fetch, caption_fn, event_id, masterdoc) -> dict` — fetches files in order, enriches, saves `guide.md`, updates `event.json` status to `"ready"`, returns `{"files": n, "images": n}`
  - `caption_fn` signature: `(image_bytes: bytes, mime: str) -> str`
- Consumes: Task 2 `Storage`/`get_event`, Task 3 helpers.

- [ ] **Step 1: Write the failing tests** (append to `orchestrator/tests/test_ingest.py`)

```python
import json
from app.ingest import enrich_markdown, ingest_event
from app.storage import LocalStorage, create_event, get_event

def fake_fetch_factory(pages: dict):
    def fetch(url: str) -> bytes:
        return pages[url]
    return fetch

def fake_caption(image_bytes: bytes, mime: str = "image/png") -> str:
    return f"caption-for-{len(image_bytes)}-bytes"

def test_enrich_markdown_inlines_caption_and_url():
    md = "step 1\n\n![](../images/a.png)\n\nstep 2"
    pages = {"https://x/images/a.png": b"12345"}
    out = enrich_markdown(md, "https://x/Labs/e1.md", fake_fetch_factory(pages), fake_caption, {})
    assert "![](../images/a.png)" in out
    assert "> [Screenshot] caption-for-5-bytes" in out
    assert "> (image: https://x/images/a.png)" in out

def test_enrich_markdown_caches_duplicate_images():
    md = "![](../images/a.png)\n![](../images/a.png)"
    calls = []
    def counting_caption(b, mime="image/png"):
        calls.append(1)
        return "cap"
    pages = {"https://x/images/a.png": b"1"}
    enrich_markdown(md, "https://x/Labs/e1.md", fake_fetch_factory(pages), counting_caption, {})
    assert len(calls) == 1

def test_enrich_markdown_survives_broken_image():
    def broken_fetch(url):
        raise IOError("404")
    out = enrich_markdown("![](../images/gone.png)", "https://x/Labs/e1.md", broken_fetch, fake_caption, {})
    assert "unavailable" in out

def test_ingest_event_end_to_end(tmp_path):
    storage = LocalStorage(str(tmp_path))
    ev = create_event(storage, "demo")
    masterdoc = [{"Name": "demo", "Files": [
        {"RawFilePath": "https://x/Labs/e1.md", "Order": 1},
        {"RawFilePath": "https://x/Labs/e2.md", "Order": 2},
    ]}]
    pages = {
        "https://x/Labs/e1.md": b"# Ex1\n![](../images/a.png)",
        "https://x/Labs/e2.md": b"# Ex2\nno images",
        "https://x/images/a.png": b"123",
    }
    stats = ingest_event(storage, fake_fetch_factory(pages), fake_caption, ev["event_id"], masterdoc)
    assert stats == {"files": 2, "images": 1}
    guide = storage.load_text(ev["event_id"], "guide.md")
    assert "# Ex1" in guide and "# Ex2" in guide
    assert guide.index("# Ex1") < guide.index("# Ex2")
    assert "caption-for-3-bytes" in guide
    assert get_event(storage, ev["event_id"])["status"] == "ready"
```

- [ ] **Step 2: Run tests** → FAIL (functions missing).

- [ ] **Step 3: Implement** (append to `orchestrator/app/ingest.py`)

```python
import json as _json

def _mime_for(url: str) -> str:
    return "image/jpeg" if url.lower().endswith((".jpg", ".jpeg")) else "image/png"

def enrich_markdown(md: str, base_url: str, fetch, caption_fn, cache: dict) -> str:
    def repl(m):
        ref = m.group(1)
        resolved = resolve_ref(base_url, ref)
        if resolved not in cache:
            try:
                cache[resolved] = caption_fn(fetch(resolved), mime=_mime_for(resolved))
            except Exception:
                cache[resolved] = "screenshot unavailable"
        return f"{m.group(0)}\n> [Screenshot] {cache[resolved]}\n> (image: {resolved})"
    return IMG_RE.sub(repl, md)

def ingest_event(storage, fetch, caption_fn, event_id: str, masterdoc) -> dict:
    from app.storage import get_event
    cache: dict = {}
    parts = []
    for url in ordered_paths(masterdoc):
        md = fetch(url).decode("utf-8")
        parts.append(enrich_markdown(md, url, fetch, caption_fn, cache))
    storage.save_text(event_id, "guide.md", "\n\n---\n\n".join(parts))
    event = get_event(storage, event_id)
    event["status"] = "ready"
    storage.save_text(event_id, "event.json", _json.dumps(event))
    return {"files": len(parts), "images": len(cache)}
```

- [ ] **Step 4: Run tests** → `python -m pytest tests/test_ingest.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add orchestrator/app/ingest.py orchestrator/tests/test_ingest.py
git commit -m "feat: enrichment pipeline with caption cache and ordered assembly"
```

---

### Task 6: MS Learn client

**Files:**
- Create: `orchestrator/app/mslearn.py`, `orchestrator/tests/test_mslearn.py`

**Interfaces:**
- Produces: `search_learn(question: str, top: int = 3, get_json=None) -> list[dict]` — each `{"title","url","summary"}`; returns `[]` on any failure (Q&A degrades gracefully). `get_json` injectable for tests; default uses httpx against `https://learn.microsoft.com/api/search`.

- [ ] **Step 1: Write the failing tests**

`orchestrator/tests/test_mslearn.py`:
```python
from app.mslearn import search_learn

def test_search_learn_maps_results():
    def fake_get_json(url, params):
        assert params["search"] == "create storage account"
        return {"results": [
            {"title": "Create a storage account", "url": "https://learn.microsoft.com/x", "description": "How to."},
        ]}
    out = search_learn("create storage account", get_json=fake_get_json)
    assert out == [{"title": "Create a storage account",
                    "url": "https://learn.microsoft.com/x",
                    "summary": "How to."}]

def test_search_learn_swallows_errors():
    def boom(url, params):
        raise IOError("down")
    assert search_learn("anything", get_json=boom) == []
```

- [ ] **Step 2: Run tests** → FAIL.

- [ ] **Step 3: Implement**

`orchestrator/app/mslearn.py`:
```python
import httpx

SEARCH_URL = "https://learn.microsoft.com/api/search"

def _default_get_json(url: str, params: dict) -> dict:
    r = httpx.get(url, params=params, timeout=10)
    r.raise_for_status()
    return r.json()

def search_learn(question: str, top: int = 3, get_json=None) -> list[dict]:
    get_json = get_json or _default_get_json
    try:
        data = get_json(SEARCH_URL, {"search": question, "locale": "en-us", "$top": top})
        return [
            {"title": r.get("title", ""), "url": r.get("url", ""),
             "summary": r.get("description") or r.get("summary") or ""}
            for r in data.get("results", [])[:top]
        ]
    except Exception:
        return []  # Q&A still works from the guide alone
```

- [ ] **Step 4: Run tests** → PASS.

- [ ] **Step 5: Commit**

```bash
git add orchestrator/app/mslearn.py orchestrator/tests/test_mslearn.py
git commit -m "feat: MS Learn search client with graceful degradation"
```

---

### Task 7: Metering

**Files:**
- Create: `orchestrator/app/metering.py`, `orchestrator/tests/test_metering.py`

**Interfaces:**
- Produces: `record(storage, event_id, deployment_id, tokens_in: int, tokens_out: int, now=None)` — appends one JSON line to `usage.jsonl`; `read_usage(storage, event_id) -> list[dict]`.
- Consumes: Task 2 `Storage.append_line` / `load_text`.

- [ ] **Step 1: Write the failing test**

`orchestrator/tests/test_metering.py`:
```python
from app.metering import record, read_usage
from app.storage import LocalStorage

def test_record_appends_json_lines(tmp_path):
    s = LocalStorage(str(tmp_path))
    record(s, "ev1", "dep-123", 900, 150, now=1720000000.0)
    record(s, "ev1", "dep-456", 800, 100, now=1720000001.0)
    rows = read_usage(s, "ev1")
    assert rows == [
        {"event_id": "ev1", "deployment_id": "dep-123", "ts": 1720000000.0, "tokens_in": 900, "tokens_out": 150},
        {"event_id": "ev1", "deployment_id": "dep-456", "ts": 1720000001.0, "tokens_in": 800, "tokens_out": 100},
    ]

def test_read_usage_empty(tmp_path):
    assert read_usage(LocalStorage(str(tmp_path)), "ev1") == []
```

- [ ] **Step 2: Run test** → FAIL.

- [ ] **Step 3: Implement**

`orchestrator/app/metering.py`:
```python
import json
import time

def record(storage, event_id: str, deployment_id: str,
           tokens_in: int, tokens_out: int, now: float | None = None) -> None:
    row = {"event_id": event_id, "deployment_id": deployment_id,
           "ts": now if now is not None else time.time(),
           "tokens_in": tokens_in, "tokens_out": tokens_out}
    storage.append_line(event_id, "usage.jsonl", json.dumps(row))

def read_usage(storage, event_id: str) -> list[dict]:
    try:
        text = storage.load_text(event_id, "usage.jsonl")
    except KeyError:
        return []
    return [json.loads(l) for l in text.splitlines() if l.strip()]
```

- [ ] **Step 4: Run test** → PASS.

- [ ] **Step 5: Commit**

```bash
git add orchestrator/app/metering.py orchestrator/tests/test_metering.py
git commit -m "feat: append-only metering log"
```

---

### Task 8: API — create event + ingest endpoints

**Files:**
- Modify: `orchestrator/app/main.py`
- Create: `orchestrator/tests/test_api_events.py`

**Interfaces:**
- Produces:
  - `POST /api/events` body `{"name": str}` → 200 `{"event_id","key","name","status"}`
  - `POST /api/events/{event_id}/ingest` header `X-Event-Key`, body `{"masterdoc_url": str}` **or** `{"masterdoc": <parsed json>}` → 200 `{"files","images"}`; 401 bad key; 404 unknown event
  - App-level dependency wiring: `app.state.storage`, `app.state.fetch`, `app.state.caption_fn`, `app.state.oai` — overridable in tests.
- Consumes: Tasks 2–5.

- [ ] **Step 1: Write the failing tests**

`orchestrator/tests/test_api_events.py`:
```python
import json
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.storage import LocalStorage

@pytest.fixture
def client(tmp_path):
    app.state.storage = LocalStorage(str(tmp_path))
    pages = {
        "https://x/masterdoc.json": json.dumps([{"Name": "d", "Files": [
            {"RawFilePath": "https://x/Labs/e1.md", "Order": 1}]}]).encode(),
        "https://x/Labs/e1.md": b"# Ex1\n![](../images/a.png)",
        "https://x/images/a.png": b"123",
    }
    app.state.fetch = lambda url: pages[url]
    app.state.caption_fn = lambda b, mime="image/png": "fake caption"
    return TestClient(app)

def test_create_event(client):
    r = client.post("/api/events", json={"name": "AI Workshop"})
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "AI Workshop" and body["event_id"] and body["key"]

def test_ingest_via_masterdoc_url(client):
    ev = client.post("/api/events", json={"name": "d"}).json()
    r = client.post(f"/api/events/{ev['event_id']}/ingest",
                    json={"masterdoc_url": "https://x/masterdoc.json"},
                    headers={"X-Event-Key": ev["key"]})
    assert r.status_code == 200
    assert r.json() == {"files": 1, "images": 1}

def test_ingest_wrong_key_401(client):
    ev = client.post("/api/events", json={"name": "d"}).json()
    r = client.post(f"/api/events/{ev['event_id']}/ingest",
                    json={"masterdoc_url": "https://x/masterdoc.json"},
                    headers={"X-Event-Key": "nope"})
    assert r.status_code == 401

def test_ingest_unknown_event_404(client):
    r = client.post("/api/events/deadbeef/ingest",
                    json={"masterdoc_url": "https://x/masterdoc.json"},
                    headers={"X-Event-Key": "k"})
    assert r.status_code == 404
```

- [ ] **Step 2: Run tests** → FAIL (404s on routes).

- [ ] **Step 3: Implement** — replace `orchestrator/app/main.py`:

```python
import json

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from app.config import get_settings
from app import ingest as ingest_mod
from app.storage import create_event, get_event, get_storage, verify_key

app = FastAPI(title="CloudLabs Lab Assistant Orchestrator")

@app.on_event("startup")
def _wire():
    settings = get_settings()
    if not hasattr(app.state, "storage"):
        app.state.storage = get_storage(settings)
    if not hasattr(app.state, "fetch"):
        app.state.fetch = ingest_mod.http_fetch
    if not hasattr(app.state, "caption_fn"):
        from app.captioner import Captioner, make_openai_client
        oai = make_openai_client(settings)
        app.state.oai = oai
        app.state.caption_fn = Captioner(oai, settings.azure_openai_chat_deployment).caption

@app.get("/healthz")
def healthz():
    return {"status": "ok"}

class CreateEventRequest(BaseModel):
    name: str

@app.post("/api/events")
def create_event_endpoint(req: CreateEventRequest):
    return create_event(app.state.storage, req.name)

class IngestRequest(BaseModel):
    masterdoc_url: str | None = None
    masterdoc: list | dict | None = None

def _check_event(event_id: str, key: str):
    if get_event(app.state.storage, event_id) is None:
        raise HTTPException(404, "unknown event")
    if not verify_key(app.state.storage, event_id, key):
        raise HTTPException(401, "bad event key")

@app.post("/api/events/{event_id}/ingest")
def ingest_endpoint(event_id: str, req: IngestRequest,
                    x_event_key: str = Header(default="")):
    _check_event(event_id, x_event_key)
    masterdoc = req.masterdoc
    if masterdoc is None:
        if not req.masterdoc_url:
            raise HTTPException(422, "masterdoc or masterdoc_url required")
        masterdoc = json.loads(app.state.fetch(req.masterdoc_url).decode("utf-8"))
    return ingest_mod.ingest_event(app.state.storage, app.state.fetch,
                                   app.state.caption_fn, event_id, masterdoc)
```

Note: `TestClient` triggers `startup` after fixtures set `app.state`, and the `hasattr` guards keep test doubles in place.

- [ ] **Step 4: Run tests** → `python -m pytest tests/ -v` → all PASS.

- [ ] **Step 5: Commit**

```bash
git add orchestrator/app/main.py orchestrator/tests/test_api_events.py
git commit -m "feat: event creation and ingest endpoints"
```

---

### Task 9: Query endpoint (grounded Q&A + metering)

**Files:**
- Modify: `orchestrator/app/main.py`
- Create: `orchestrator/app/query.py`, `orchestrator/tests/test_api_query.py`

**Interfaces:**
- Produces:
  - `app.query.SYSTEM_PROMPT_TEMPLATE` and `build_messages(guide, learn_results, question) -> list[dict]`
  - `POST /api/query` header `X-Event-Key`, body `{"event_id","deployment_id","question"}` → `{"answer": str, "sources": [{"title","url","summary"}]}`; 401/404 as Task 8; 409 if guide not ingested. Records metering per Global Constraints.
- Consumes: Tasks 2, 6, 7, 8.

- [ ] **Step 1: Write the failing tests**

`orchestrator/tests/test_api_query.py`:
```python
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.metering import read_usage
from app.storage import LocalStorage

class FakeUsage:
    prompt_tokens = 900
    completion_tokens = 120

class FakeCompletions:
    def create(self, **kwargs):
        self.last_kwargs = kwargs
        class Msg: content = "Look under Exercise 1, Task 2 — the option is in the left menu."
        class Choice: message = Msg()
        class Resp:
            choices = [Choice()]
            usage = FakeUsage()
        return Resp()

class FakeOAI:
    def __init__(self):
        self.chat = type("C", (), {"completions": FakeCompletions()})()

@pytest.fixture
def client(tmp_path):
    app.state.storage = LocalStorage(str(tmp_path))
    app.state.fetch = lambda url: b""
    app.state.caption_fn = lambda b, mime="image/png": "cap"
    app.state.oai = FakeOAI()
    app.state.learn_search = lambda q: [
        {"title": "Doc", "url": "https://learn.microsoft.com/d", "summary": "s"}]
    return TestClient(app)

def _make_ready_event(client):
    ev = client.post("/api/events", json={"name": "d"}).json()
    app.state.storage.save_text(ev["event_id"], "guide.md", "# Exercise 1\nTask 2: click the left menu")
    return ev

def test_query_answers_and_meters(client):
    ev = _make_ready_event(client)
    r = client.post("/api/query",
                    json={"event_id": ev["event_id"], "deployment_id": "dep-1",
                          "question": "stuck on task 2"},
                    headers={"X-Event-Key": ev["key"]})
    assert r.status_code == 200
    assert "Exercise 1" in r.json()["answer"]
    assert r.json()["sources"][0]["url"] == "https://learn.microsoft.com/d"
    rows = read_usage(app.state.storage, ev["event_id"])
    assert rows[0]["deployment_id"] == "dep-1"
    assert rows[0]["tokens_in"] == 900 and rows[0]["tokens_out"] == 120

def test_query_guide_in_system_prompt(client):
    ev = _make_ready_event(client)
    client.post("/api/query",
                json={"event_id": ev["event_id"], "deployment_id": "d", "question": "q"},
                headers={"X-Event-Key": ev["key"]})
    sent = app.state.oai.chat.completions.last_kwargs["messages"]
    assert sent[0]["role"] == "system"
    assert "click the left menu" in sent[0]["content"]      # guide stuffed
    assert "never perform" in sent[0]["content"].lower()     # guardrail present

def test_query_before_ingest_409(client):
    ev = client.post("/api/events", json={"name": "d"}).json()
    r = client.post("/api/query",
                    json={"event_id": ev["event_id"], "deployment_id": "d", "question": "q"},
                    headers={"X-Event-Key": ev["key"]})
    assert r.status_code == 409

def test_query_wrong_key_401(client):
    ev = _make_ready_event(client)
    r = client.post("/api/query",
                    json={"event_id": ev["event_id"], "deployment_id": "d", "question": "q"},
                    headers={"X-Event-Key": "bad"})
    assert r.status_code == 401
```

- [ ] **Step 2: Run tests** → FAIL.

- [ ] **Step 3: Implement**

`orchestrator/app/query.py`:
```python
SYSTEM_PROMPT_TEMPLATE = """You are the CloudLabs Lab Assistant, embedded in a learner's lab VM.

Rules:
- Answer ONLY from the LAB GUIDE below and the MS LEARN EXCERPTS. If neither
  covers the question, say so and suggest contacting the instructor.
- Explain and point to where things are. NEVER perform steps for the learner,
  never output complete solutions that bypass the learning objective.
- Cite where your answer comes from (e.g. "Exercise 1, Task 2, step 3").
- Text like <inject key="Deployment ID"/> is a per-learner placeholder: tell the
  learner to use the value from their Environment Details tab, not the literal text.
- Lines starting with "> [Screenshot]" describe the guide's screenshots — use them
  to tell the learner what the screen should look like.

LAB GUIDE:
{guide}

MS LEARN EXCERPTS:
{learn}
"""

def build_messages(guide: str, learn_results: list[dict], question: str) -> list[dict]:
    learn = "\n".join(
        f"- {r['title']} ({r['url']}): {r['summary']}" for r in learn_results
    ) or "(none found)"
    return [
        {"role": "system", "content": SYSTEM_PROMPT_TEMPLATE.format(guide=guide, learn=learn)},
        {"role": "user", "content": question},
    ]
```

Append to `orchestrator/app/main.py`:
```python
from app import metering
from app.mslearn import search_learn
from app.query import build_messages

class QueryRequest(BaseModel):
    event_id: str
    deployment_id: str
    question: str

@app.post("/api/query")
def query_endpoint(req: QueryRequest, x_event_key: str = Header(default="")):
    _check_event(req.event_id, x_event_key)
    storage = app.state.storage
    try:
        guide = storage.load_text(req.event_id, "guide.md")
    except KeyError:
        raise HTTPException(409, "event not ingested yet")
    learn_search = getattr(app.state, "learn_search", search_learn)
    learn_results = learn_search(req.question)
    settings = get_settings()
    resp = app.state.oai.chat.completions.create(
        model=settings.azure_openai_chat_deployment,
        messages=build_messages(guide, learn_results, req.question),
        max_tokens=800,
    )
    usage = resp.usage
    metering.record(storage, req.event_id, req.deployment_id,
                    usage.prompt_tokens, usage.completion_tokens)
    return {"answer": resp.choices[0].message.content, "sources": learn_results}
```

- [ ] **Step 4: Run tests** → `python -m pytest tests/ -v` → all PASS.

- [ ] **Step 5: Commit**

```bash
git add orchestrator/app/query.py orchestrator/app/main.py orchestrator/tests/test_api_query.py
git commit -m "feat: grounded query endpoint with metering"
```

---

### Task 10: Instructor portal page

**Files:**
- Create: `orchestrator/app/portal/index.html`
- Modify: `orchestrator/app/main.py` (serve portal + static)
- Create: `orchestrator/tests/test_portal.py`

**Interfaces:**
- Produces: `GET /` serves the portal HTML; `GET /download/sidecar.zip` serves `orchestrator/static/sidecar.zip` (built in Task 12). Portal flow: create event → paste masterdoc URL → ingest → display `eventID / endpoint / key` + the exact ARM parameter values to paste into CloudLabs.

- [ ] **Step 1: Write the failing test**

`orchestrator/tests/test_portal.py`:
```python
from fastapi.testclient import TestClient
from app.main import app
from app.storage import LocalStorage

def test_portal_served(tmp_path):
    app.state.storage = LocalStorage(str(tmp_path))
    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200
    assert "Lab Assistant" in r.text
```

- [ ] **Step 2: Run test** → FAIL (404).

- [ ] **Step 3: Implement**

`orchestrator/app/portal/index.html`:
```html
<!doctype html>
<meta charset="utf-8">
<title>CloudLabs Lab Assistant — Instructor Portal</title>
<style>
  body{font-family:system-ui;max-width:720px;margin:3rem auto;padding:0 1rem}
  input,button{font:inherit;padding:.5rem}
  input{width:100%;box-sizing:border-box;margin:.25rem 0}
  pre{background:#f4f4f4;padding:1rem;overflow-x:auto}
  .step{margin:1.5rem 0}
</style>
<h1>Lab Assistant — Instructor Portal</h1>

<div class="step">
  <h2>1. Create lab event</h2>
  <input id="name" placeholder="Event name, e.g. AI Foundry Workshop — 2026-07-10">
  <button onclick="createEvent()">Create</button>
</div>

<div class="step">
  <h2>2. Ingest lab guide</h2>
  <input id="masterdoc" placeholder="Masterdoc URL (raw masterdoc.json)">
  <button onclick="ingest()">Ingest</button>
  <span id="ingest-status"></span>
</div>

<div class="step">
  <h2>3. CloudLabs ARM parameters</h2>
  <pre id="out">Create an event first.</pre>
</div>

<script>
let ev = null;
async function createEvent() {
  const r = await fetch('/api/events', {method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({name: document.getElementById('name').value})});
  ev = await r.json();
  render('event created — now ingest the guide');
}
async function ingest() {
  if (!ev) return alert('create an event first');
  document.getElementById('ingest-status').textContent = 'ingesting…';
  const r = await fetch(`/api/events/${ev.event_id}/ingest`, {method:'POST',
    headers:{'Content-Type':'application/json','X-Event-Key': ev.key},
    body: JSON.stringify({masterdoc_url: document.getElementById('masterdoc').value})});
  const body = await r.json();
  document.getElementById('ingest-status').textContent =
    r.ok ? `done: ${body.files} files, ${body.images} images` : `error: ${JSON.stringify(body)}`;
  if (r.ok) render('guide ready');
}
function render(status) {
  document.getElementById('out').textContent =
`status: ${status}
sidecarEventID:  ${ev.event_id}
sidecarEndpoint: ${location.origin}
sidecarKey:      ${ev.key}`;
}
</script>
```

In `orchestrator/app/main.py`, add:
```python
from pathlib import Path
from fastapi.responses import FileResponse, HTMLResponse

PORTAL = Path(__file__).parent / "portal" / "index.html"
STATIC = Path(__file__).parent.parent / "static"

@app.get("/", response_class=HTMLResponse)
def portal():
    return PORTAL.read_text(encoding="utf-8")

@app.get("/download/sidecar.zip")
def download_sidecar():
    f = STATIC / "sidecar.zip"
    if not f.exists():
        raise HTTPException(404, "sidecar.zip not built yet")
    return FileResponse(f, media_type="application/zip", filename="sidecar.zip")
```

- [ ] **Step 4: Run tests** → all PASS.

- [ ] **Step 5: Commit**

```bash
git add orchestrator/app/portal/index.html orchestrator/app/main.py orchestrator/tests/test_portal.py
git commit -m "feat: instructor portal page and sidecar download route"
```

---

### Task 11: Go sidecar

**Files:**
- Create: `sidecar/go.mod`, `sidecar/main.go`, `sidecar/ui/index.html`, `sidecar/main_test.go`

**Interfaces:**
- Consumes: orchestrator `POST /api/query` (Task 9) with header `X-Event-Key`.
- Produces:
  - `config.json` schema (stamped by Task 12 PowerShell): `{"endpoint": "https://…", "event_id": "…", "key": "…"}`
  - Local server `127.0.0.1:7788`: `GET /` chat UI; `POST /ask` body `{"question": str}` → orchestrator response passthrough.
  - `loadConfig(path string) (Config, error)`; `newAskHandler(cfg Config, client *http.Client) http.HandlerFunc`.

- [ ] **Step 1: Write the failing tests**

`sidecar/main_test.go`:
```go
package main

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestLoadConfig(t *testing.T) {
	dir := t.TempDir()
	p := filepath.Join(dir, "config.json")
	os.WriteFile(p, []byte(`{"endpoint":"https://orch","event_id":"ev1","key":"k1"}`), 0o644)
	cfg, err := loadConfig(p)
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Endpoint != "https://orch" || cfg.EventID != "ev1" || cfg.Key != "k1" {
		t.Fatalf("bad config: %+v", cfg)
	}
}

func TestAskHandlerProxiesToOrchestrator(t *testing.T) {
	var gotPath, gotKey string
	var gotBody map[string]any
	orch := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotPath = r.URL.Path
		gotKey = r.Header.Get("X-Event-Key")
		b, _ := io.ReadAll(r.Body)
		json.Unmarshal(b, &gotBody)
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"answer":"look left","sources":[]}`))
	}))
	defer orch.Close()

	cfg := Config{Endpoint: orch.URL, EventID: "ev1", Key: "k1", DeploymentID: "dep-9"}
	h := newAskHandler(cfg, orch.Client())
	req := httptest.NewRequest("POST", "/ask", strings.NewReader(`{"question":"where is it"}`))
	rec := httptest.NewRecorder()
	h(rec, req)

	if gotPath != "/api/query" {
		t.Fatalf("path = %s", gotPath)
	}
	if gotKey != "k1" {
		t.Fatalf("key = %s", gotKey)
	}
	if gotBody["event_id"] != "ev1" || gotBody["deployment_id"] != "dep-9" || gotBody["question"] != "where is it" {
		t.Fatalf("body = %v", gotBody)
	}
	if !strings.Contains(rec.Body.String(), "look left") {
		t.Fatalf("response = %s", rec.Body.String())
	}
}
```

- [ ] **Step 2: Run tests** → `cd sidecar && go test ./...` → FAIL (no code).

- [ ] **Step 3: Implement**

`sidecar/go.mod`:
```
module cloudlabs/sidecar

go 1.22
```

`sidecar/main.go`:
```go
package main

import (
	"bytes"
	"embed"
	"encoding/json"
	"io"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"time"
)

//go:embed ui/index.html
var ui embed.FS

type Config struct {
	Endpoint     string `json:"endpoint"`
	EventID      string `json:"event_id"`
	Key          string `json:"key"`
	DeploymentID string `json:"deployment_id"`
}

func loadConfig(path string) (Config, error) {
	var cfg Config
	b, err := os.ReadFile(path)
	if err != nil {
		return cfg, err
	}
	err = json.Unmarshal(b, &cfg)
	if cfg.DeploymentID == "" {
		host, _ := os.Hostname()
		cfg.DeploymentID = host // labvm-{DeploymentID} per ARM naming
	}
	return cfg, err
}

func newAskHandler(cfg Config, client *http.Client) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var in struct {
			Question string `json:"question"`
		}
		if err := json.NewDecoder(r.Body).Decode(&in); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}
		payload, _ := json.Marshal(map[string]string{
			"event_id":      cfg.EventID,
			"deployment_id": cfg.DeploymentID,
			"question":      in.Question,
		})
		req, _ := http.NewRequest("POST", cfg.Endpoint+"/api/query", bytes.NewReader(payload))
		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("X-Event-Key", cfg.Key)
		resp, err := client.Do(req)
		if err != nil {
			http.Error(w, "orchestrator unreachable: "+err.Error(), http.StatusBadGateway)
			return
		}
		defer resp.Body.Close()
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(resp.StatusCode)
		io.Copy(w, resp.Body)
	}
}

func main() {
	exe, _ := os.Executable()
	cfg, err := loadConfig(filepath.Join(filepath.Dir(exe), "config.json"))
	if err != nil {
		log.Fatalf("config.json: %v", err)
	}
	client := &http.Client{Timeout: 60 * time.Second}
	http.Handle("/", http.FileServer(http.FS(mustSub())))
	http.HandleFunc("/ask", newAskHandler(cfg, client))
	log.Println("Lab Assistant on http://127.0.0.1:7788")
	log.Fatal(http.ListenAndServe("127.0.0.1:7788", nil))
}

func mustSub() http.FileSystem {
	return http.FS(mustFS())
}

func mustFS() fsWrap { return fsWrap{} }

type fsWrap struct{}

func (fsWrap) Open(name string) (http.File, error) {
	f, err := http.FS(ui).Open("ui/index.html")
	return f, err
}
```

`ponytail: fsWrap serves index.html for every path — one page, no router needed.`

`sidecar/ui/index.html`:
```html
<!doctype html>
<meta charset="utf-8">
<title>Lab Assistant</title>
<style>
  body{font-family:system-ui;max-width:680px;margin:2rem auto;padding:0 1rem}
  #log{border:1px solid #ddd;border-radius:8px;padding:1rem;min-height:300px;
       white-space:pre-wrap}
  .q{color:#0b5cad;margin:.75rem 0 .25rem;font-weight:600}
  .a{margin:0 0 .75rem}
  .src{font-size:.85em;color:#666}
  form{display:flex;gap:.5rem;margin-top:1rem}
  input{flex:1;font:inherit;padding:.6rem}
  button{font:inherit;padding:.6rem 1.2rem}
</style>
<h1>🛟 Lab Assistant</h1>
<p>Stuck on a task? Ask — answers come from <em>your</em> lab guide and MS Learn.
I explain and point; I won't do the steps for you.</p>
<div id="log"></div>
<form onsubmit="ask(event)">
  <input id="q" placeholder="e.g. I'm stuck on Task 2, I can't find the option" autofocus>
  <button>Ask</button>
</form>
<script>
async function ask(e) {
  e.preventDefault();
  const q = document.getElementById('q').value.trim();
  if (!q) return;
  const log = document.getElementById('log');
  log.insertAdjacentHTML('beforeend', `<div class="q">You: ${esc(q)}</div><div class="a">…</div>`);
  document.getElementById('q').value = '';
  const slot = log.lastElementChild;
  try {
    const r = await fetch('/ask', {method:'POST',
      headers:{'Content-Type':'application/json'}, body: JSON.stringify({question:q})});
    const body = await r.json();
    if (!r.ok) throw new Error(body.detail || r.status);
    slot.textContent = body.answer;
    if (body.sources?.length)
      slot.insertAdjacentHTML('afterend', '<div class="src">MS Learn: ' +
        body.sources.map(s=>`<a href="${s.url}" target="_blank">${esc(s.title)}</a>`).join(' · ') + '</div>');
  } catch (err) { slot.textContent = 'Error: ' + err.message; }
  log.scrollTop = log.scrollHeight;
}
const esc = s => s.replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
</script>
```

- [ ] **Step 4: Run tests** → `go test ./... -v` → PASS. Also `go vet ./...` clean.

- [ ] **Step 5: Commit**

```bash
git add sidecar/
git commit -m "feat: Go sidecar with embedded chat UI and orchestrator proxy"
```

---

### Task 12: Sidecar build script + PowerShell install + ARM wiring

**Files:**
- Create: `sidecar/build.ps1`, `scripts/InstallSidecarAgent.ps1`, `scripts/arm-snippet.md`, `scripts/demo-integration.md`

**Interfaces:**
- Consumes: Task 11 binary; Task 10 `/download/sidecar.zip` route.
- Produces: `orchestrator/static/sidecar.zip` (contains `sidecar.exe`); `InstallSidecarAgent -SidecarEventID x -SidecarEndpoint url -SidecarKey k` PowerShell function; documented ARM param wiring.

- [ ] **Step 1: Write `sidecar/build.ps1`**

```powershell
# Builds the sidecar for Windows and drops sidecar.zip where the orchestrator serves it.
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
$env:GOOS = 'windows'; $env:GOARCH = 'amd64'; $env:CGO_ENABLED = '0'
go build -ldflags '-s -w' -o sidecar.exe .
$staticDir = Join-Path $PSScriptRoot '..\orchestrator\static'
New-Item -ItemType Directory -Force $staticDir | Out-Null
Compress-Archive -Path .\sidecar.exe -DestinationPath (Join-Path $staticDir 'sidecar.zip') -Force
Remove-Item .\sidecar.exe
Pop-Location
Write-Host 'Built orchestrator/static/sidecar.zip'
```

- [ ] **Step 2: Write `scripts/InstallSidecarAgent.ps1`**

The function to merge into `cloudlabs-windows-functions.ps1` (same idiom as `InstallModernVmValidator` + `CreateCredFile`):

```powershell
# CloudLabs Lab Assistant sidecar agent.
# Merge into cloudlabs-windows-functions.ps1; call from the lab's logon script:
#   InstallSidecarAgent -SidecarEventID $SidecarEventID -SidecarEndpoint $SidecarEndpoint -SidecarKey $SidecarKey -DeploymentID $DeploymentID
Function InstallSidecarAgent
{
    Param (
        [Parameter(Mandatory = $true)][string]$SidecarEventID,
        [Parameter(Mandatory = $true)][string]$SidecarEndpoint,
        [Parameter(Mandatory = $true)][string]$SidecarKey,
        [string]$DeploymentID = $env:ComputerName
    )
    $dir = 'C:\CloudLabs\Sidecar'
    New-Item -ItemType Directory -Path $dir -Force | Out-Null

    # 1. Fetch the agent from the orchestrator itself
    Invoke-WebRequest "$SidecarEndpoint/download/sidecar.zip" -OutFile "$dir\sidecar.zip" -UseBasicParsing
    Expand-Archive -LiteralPath "$dir\sidecar.zip" -DestinationPath $dir -Force

    # 2. Stamp per-event config (CreateCredFile idiom, but JSON)
    @{
        endpoint      = $SidecarEndpoint
        event_id      = $SidecarEventID
        key           = $SidecarKey
        deployment_id = $DeploymentID
    } | ConvertTo-Json | Set-Content "$dir\config.json" -Encoding ascii

    # 3. Run at every logon (Enable-CloudLabsEmbeddedShadow idiom)
    #    ponytail: scheduled task instead of a Windows service — zero service
    #    plumbing in the binary; upgrade to sc create if lifecycle control is needed.
    $Action  = New-ScheduledTaskAction -Execute "$dir\sidecar.exe"
    $Trigger = New-ScheduledTaskTrigger -AtLogOn
    Register-ScheduledTask -TaskName 'CloudLabsLabAssistant' -Action $Action `
        -Trigger $Trigger -RunLevel Limited -Force
    Start-Process "$dir\sidecar.exe" -WindowStyle Hidden

    # 4. Desktop shortcut to the local UI
    Set-Content 'C:\Users\Public\Desktop\Lab Assistant.url' @'
[InternetShortcut]
URL=http://127.0.0.1:7788
'@
}
```

- [ ] **Step 3: Write `scripts/arm-snippet.md`**

````markdown
# Wiring the Lab Assistant into a CloudLabs deployment

## 1. deploy.json — add parameters

```json
"sidecarEventID":  { "type": "string" },
"sidecarEndpoint": { "type": "string" },
"sidecarKey":      { "type": "securestring" }
```

## 2. deploy.json — add variable (next to `cloudlabsCommon`)

```json
"sidecarArgs": "[concat(' -SidecarEventID ', parameters('sidecarEventID'), ' -SidecarEndpoint ', parameters('sidecarEndpoint'), ' -SidecarKey ', parameters('sidecarKey'))]"
```

## 3. deploy.json — thread into commandToExecute

```json
"commandToExecute": "[concat('powershell.exe -ExecutionPolicy Unrestricted -File <labscript>.ps1', variables('cloudlabsCommon'), variables('Enable-CloudLabsEmbeddedShadow'), variables('sidecarArgs'))]"
```

## 4. Where the values come from

The instructor portal (step 3 on the page) prints exactly these three values
after ingest. Paste them into the CloudLabs template parameters before
launching the event.
````

- [ ] **Step 4: Write `scripts/demo-integration.md`**

````markdown
# demo.ps1 integration

Add the three params to the `Param()` block:

```powershell
[string]$SidecarEventID,
[string]$SidecarEndpoint,
[string]$SidecarKey
```

Add one line after the choco installs (requires InstallSidecarAgent merged
into cloudlabs-windows-functions.ps1):

```powershell
InstallSidecarAgent -SidecarEventID $SidecarEventID -SidecarEndpoint $SidecarEndpoint -SidecarKey $SidecarKey -DeploymentID $DeploymentID
```
````

- [ ] **Step 5: Verify build works**

Run: `pwsh sidecar/build.ps1`
Expected: `Built orchestrator/static/sidecar.zip`; file exists.
Then: start orchestrator (`uvicorn app.main:app` from `orchestrator/`), `curl -I http://127.0.0.1:8000/download/sidecar.zip` → 200.

- [ ] **Step 6: Commit**

```bash
git add sidecar/build.ps1 scripts/
git commit -m "feat: sidecar packaging, VM install function, ARM wiring docs"
```

---

### Task 13: azd infra (Bicep)

**Files:**
- Create: `infra/main.bicep`, `infra/main.parameters.json`, `azure.yaml` (repo root)

**Interfaces:**
- Consumes: orchestrator env vars from Task 1 `Settings` (exact names, upper-cased).
- Produces: `azd up` deploys App Service (Linux, Python 3.11) + Azure OpenAI (chat deployment) + Storage account; app settings wire everything; output `ORCHESTRATOR_URL`.

- [ ] **Step 1: Write `azure.yaml`**

```yaml
name: cloudlabs-lab-assistant
services:
  orchestrator:
    project: ./orchestrator
    language: python
    host: appservice
```

- [ ] **Step 2: Write `infra/main.bicep`**

```bicep
targetScope = 'resourceGroup'

param location string = resourceGroup().location
param environmentName string
// Pin the newest GA chat model available in the region at deploy time.
// gpt-4o is the safe default; override with e.g. GPT-5.x names once confirmed GA.
param chatModelName string = 'gpt-4o'
param chatModelVersion string = '2024-11-20'
param chatDeploymentName string = 'chat'

var suffix = uniqueString(resourceGroup().id, environmentName)

resource storage 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: 'labasst${suffix}'
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
}

resource openai 'Microsoft.CognitiveServices/accounts@2023-05-01' = {
  name: 'labasst-openai-${suffix}'
  location: location
  kind: 'OpenAI'
  sku: { name: 'S0' }
  properties: {
    customSubDomainName: 'labasst-openai-${suffix}'
    publicNetworkAccess: 'Enabled'
  }
}

resource chatDeployment 'Microsoft.CognitiveServices/accounts/deployments@2023-05-01' = {
  parent: openai
  name: chatDeploymentName
  sku: { name: 'Standard', capacity: 50 }
  properties: {
    model: { format: 'OpenAI', name: chatModelName, version: chatModelVersion }
  }
}

resource plan 'Microsoft.Web/serverfarms@2023-01-01' = {
  name: 'labasst-plan-${suffix}'
  location: location
  sku: { name: 'B1' }
  kind: 'linux'
  properties: { reserved: true }
}

resource site 'Microsoft.Web/sites@2023-01-01' = {
  name: 'labasst-${suffix}'
  location: location
  tags: { 'azd-service-name': 'orchestrator' }
  properties: {
    serverFarmId: plan.id
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.11'
      appCommandLine: 'python -m uvicorn app.main:app --host 0.0.0.0 --port 8000'
      appSettings: [
        { name: 'AZURE_OPENAI_ENDPOINT', value: openai.properties.endpoint }
        { name: 'AZURE_OPENAI_API_KEY', value: openai.listKeys().key1 }
        { name: 'AZURE_OPENAI_CHAT_DEPLOYMENT', value: chatDeploymentName }
        { name: 'STORAGE_BACKEND', value: 'blob' }
        { name: 'AZURE_STORAGE_CONNECTION_STRING', value: 'DefaultEndpointsProtocol=https;AccountName=${storage.name};AccountKey=${storage.listKeys().keys[0].value};EndpointSuffix=${environment().suffixes.storage}' }
        { name: 'SCM_DO_BUILD_DURING_DEPLOYMENT', value: 'true' }
      ]
    }
    httpsOnly: true
  }
}

output ORCHESTRATOR_URL string = 'https://${site.properties.defaultHostName}'
```

- [ ] **Step 3: Write `infra/main.parameters.json`**

```json
{
  "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
  "contentVersion": "1.0.0.0",
  "parameters": {
    "environmentName": { "value": "${AZURE_ENV_NAME}" }
  }
}
```

- [ ] **Step 4: Validate**

Run: `az bicep build --file infra/main.bicep`
Expected: compiles with no errors (warnings about listKeys are acceptable).

- [ ] **Step 5: Commit**

```bash
git add azure.yaml infra/
git commit -m "feat: azd infra — App Service, Azure OpenAI, storage"
```

---

### Task 14: Local E2E harness + README

**Files:**
- Create: `scripts/local_lab_server.py`, `README.md` (replace stub)

**Interfaces:**
- Consumes: everything.
- Produces: a one-command local demo using `reference-guide/` as the lab, no CloudLabs needed.

- [ ] **Step 1: Write `scripts/local_lab_server.py`**

```python
"""Serve reference-guide/ as a fake CloudLabs docs proxy for local E2E.

Usage:  python scripts/local_lab_server.py   (serves on :9000)
Then ingest with masterdoc URL: http://127.0.0.1:9000/masterdoc.json
"""
import http.server
import json
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent / "reference-guide"
PORT = 9000

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT), **kw)

    def do_GET(self):
        if self.path == "/masterdoc.json":
            files = sorted(ROOT.glob("*.md"))
            doc = [{"Name": "Local Demo Lab", "Files": [
                {"RawFilePath": f"http://127.0.0.1:{PORT}/Labs/{f.name}", "Order": i + 1}
                for i, f in enumerate(files)]}]
            body = json.dumps(doc).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        # /Labs/x.md -> serve x.md ; ../images resolves to /images -> Images/
        self.path = re.sub(r"^/Labs/", "/", self.path)
        self.path = re.sub(r"^/images/", "/Images/", self.path, flags=re.I)
        super().do_GET()

if __name__ == "__main__":
    print(f"Fake lab guide server on http://127.0.0.1:{PORT}/masterdoc.json")
    http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
```

- [ ] **Step 2: Write `README.md`** (replace the stub)

````markdown
# CloudLabs Lab Assistant

Grounded Q&A sidecar for CloudLabs learners: a thin in-VM agent that answers
"I'm stuck on Task 2" questions from the lab's own guide + MS Learn, and never
does the lab for them. Design: `docs/superpowers/specs/2026-07-03-sidecar-agent-design.md`.

## Local demo (no Azure, except OpenAI)

```bash
# 1. env (Azure OpenAI is the only cloud dependency)
export AZURE_OPENAI_ENDPOINT=https://<your>.openai.azure.com
export AZURE_OPENAI_API_KEY=<key>
export AZURE_OPENAI_CHAT_DEPLOYMENT=<deployment>   # default gpt-4o

# 2. run the fake lab-guide server (uses reference-guide/)
python scripts/local_lab_server.py &

# 3. run the orchestrator
cd orchestrator && pip install -r requirements.txt
uvicorn app.main:app --port 8000

# 4. instructor flow: open http://127.0.0.1:8000
#    create event -> ingest http://127.0.0.1:9000/masterdoc.json -> copy values

# 5. learner flow: build + run sidecar
pwsh sidecar/build.ps1
# put the printed eventID/endpoint/key into sidecar/config.json next to the exe, run it,
# open http://127.0.0.1:7788 and ask "I'm stuck on Task 1, where do I search for AI Search?"
```

## Deploy the orchestrator (instructor, one command)

```bash
azd up          # provisions App Service + Azure OpenAI + Storage on your sub
```

## Wire a CloudLabs lab

1. Portal prints `sidecarEventID / sidecarEndpoint / sidecarKey` after ingest.
2. Merge `scripts/InstallSidecarAgent.ps1` into `cloudlabs-windows-functions.ps1`.
3. Follow `scripts/arm-snippet.md` + `scripts/demo-integration.md`.

## Tests

```bash
cd orchestrator && python -m pytest tests/ -v
cd sidecar && go test ./...
```
````

- [ ] **Step 3: Run the E2E smoke manually**

With real `AZURE_OPENAI_*` env set: follow README steps 2–5; ask a question whose
answer is in `reference-guide/Exercise-1.md` ("where do I find AI Search?");
verify the answer cites Exercise 1/Task 1 and includes MS Learn sources; verify
`data/<event_id>/usage.jsonl` has one row per question.

- [ ] **Step 4: Commit**

```bash
git add scripts/local_lab_server.py README.md
git commit -m "feat: local E2E harness and README"
```

---

### Task 15: Screen-companion backend — annotation + live screenshot support

*(Added post-approval: product owner selected Tier A + B — annotated guide screenshots and explicit one-shot live screen capture, rendered in chat. No new Azure resources; Pillow draws boxes; marker protocol instead of tool-calling.)*

**Files:**
- Create: `orchestrator/app/annotate.py`, `orchestrator/tests/test_annotate.py`
- Modify: `orchestrator/app/query.py` (system prompt + build_messages screen support), `orchestrator/app/main.py` (query endpoint), `orchestrator/requirements.txt` (add `pillow`)
- Modify: `orchestrator/tests/test_api_query.py` (annotation + screen tests)

**Interfaces:**
- Consumes: Task 9 query flow, `app.state.fetch`, `app.state.oai`.
- Produces:
  - `annotate.locate_element(client, deployment, image_bytes, target, mime="image/png") -> list[int] | None` — vision call returning `[x0,y0,x1,y1]` pixel box or None (parses `{"found":bool,"box":[...]}` JSON from the reply, `re.search` for the JSON blob).
  - `annotate.draw_box(image_bytes, box) -> bytes` — PNG with a 4px red (255,59,48) rectangle.
  - `QueryRequest` gains `screen_b64: str | None = None`. When present, the user message content becomes multimodal: `[{"type":"text","text":question},{"type":"image_url","image_url":{"url":"data:image/png;base64,<screen_b64>"}}]` via `build_messages(guide, learn, question, screen_b64=None)`.
  - System prompt addition (verbatim):
    ```
    If the learner asks WHERE something is and one of the guide's screenshots
    (the "(image: ...)" lines) shows it, end your answer with a final line:
    ANNOTATE: <that image url> | <short description of the element to highlight>
    If the learner attached their live screen and the element is visible there,
    end with: ANNOTATE: LIVE | <short description>
    Otherwise never output an ANNOTATE line.
    ```
  - Query response gains optional `"annotation": {"image_b64": str, "label": str}`; the `ANNOTATE:` line is stripped from `answer`. Marker parsing: last line startswith `ANNOTATE:`; `LIVE` uses the request's screen bytes, else `app.state.fetch(url)`. Whole annotation step wrapped in try/except — any failure returns the text answer unchanged.
- Tests: fake OAI client returning scripted responses per call (list-pop); a tiny real PNG generated with Pillow in the test; assert (1) ANNOTATE-with-url yields annotation payload and stripped answer, (2) LIVE path uses screen_b64, (3) locate-failure degrades to text-only, (4) screen_b64 produces multimodal user content.
- Commit: `feat: screen companion — guide/live annotation and screenshot queries`

### Task 16: Screen-companion sidecar — capture button + annotated-image rendering

**Files:**
- Modify: `sidecar/go.mod` (add `github.com/kbinani/screenshot`), `sidecar/main.go`, `sidecar/ui/index.html`, `sidecar/main_test.go`

**Interfaces:**
- Consumes: Task 15's `screen_b64` request field and `annotation` response field.
- Produces:
  - `newAskHandler(cfg Config, client *http.Client, capture func() (string, error)) http.HandlerFunc` — third param injectable; nil means screen capture unavailable. `/ask` body gains `"include_screen": bool`; when true and capture non-nil, its base64 PNG goes to the orchestrator as `screen_b64`. Capture errors degrade to text-only (proceed without screen, add `"screen_error"` to the proxied response envelope? No — keep passthrough pure: on capture error just omit screen_b64).
  - `captureScreen() (string, error)` — `screenshot.CaptureDisplay(0)` → PNG → base64. Called only on demand.
  - UI: "🖥 Include my screen" toggle chip by the input (active state styled, tooltip "sends a one-time screenshot of this VM's screen with your question"); message bubble shows a small "screen attached" badge; `annotation.image_b64` rendered as an `<img>` (data URL) in the assistant bubble with `label` as caption, click-to-open-full-size.
  - Existing two tests updated to pass `nil` capture; new test: `include_screen: true` with a fake capture func asserts `screen_b64` reaches the fake orchestrator; capture-error case asserts question still proxied without `screen_b64`.
- After commit, re-run `sidecar/build.ps1` so `orchestrator/static/sidecar.zip` contains the new binary.
- Commit: `feat: sidecar screen capture and annotation rendering`

## Self-Review

- **Spec coverage:** ingest (masterdoc order, dynamic image resolution, captions-at-ingest, inject tokens) → Tasks 3–5, 9; isolation/keys → Tasks 2, 8, 9; metering with `deploymentID` → Task 7, 9; portal flow → Task 10; thin sidecar on 127.0.0.1 → Task 11; VM install idiom + ARM params → Task 12; azd → Task 13; no AI Search → nowhere (correct); ephemerality → per-event storage; explicit teardown endpoint deferred (delete the RG / data dir — noted as acceptable for hackathon).
- **Deviation from spec §8:** scheduled task instead of `sc create` Windows service — flagged with a `ponytail:` comment in Task 12; upgrade path documented.
- **Preview-link resolver (spec §6 row 2):** deliberately not planned — spec §12 marks it build-time discovery pending the CloudLabs content API; masterdoc path covers the hackathon.
- **Type consistency:** `Storage` method names, `caption_fn(bytes, mime)`, `Config` JSON keys, header `X-Event-Key`, and env var names checked across tasks — consistent.
