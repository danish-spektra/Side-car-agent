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

def test_ingest_stores_inject_keys(tmp_path):
    storage = LocalStorage(str(tmp_path))
    ev = create_event(storage, "demo")
    masterdoc = [{"Name": "demo", "Files": [
        {"RawFilePath": "https://x/Labs/e1.md", "Order": 1},
    ]}]
    pages = {"https://x/Labs/e1.md":
             b'Use <inject key="Deployment ID"/> and <inject key="AzureAdUserEmail" enableCopy="true"/>.'}
    ingest_event(storage, fake_fetch_factory(pages), fake_caption, ev["event_id"], masterdoc)
    keys = json.loads(storage.load_text(ev["event_id"], "inject_keys.json"))
    assert keys == ["AzureAdUserEmail", "Deployment ID"]
