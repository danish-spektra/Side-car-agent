import base64
import json
import secrets
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from app.config import get_settings
from app import annotate as annotate_mod
from app import ingest as ingest_mod
from app import metering
from app.mslearn import search_learn
from app.query import build_messages
from app.storage import create_event, get_event, get_storage, verify_key

app = FastAPI(title="CloudLabs Lab Assistant Orchestrator")

@app.on_event("startup")
def _wire():
    settings = get_settings()
    if not hasattr(app.state, "storage"):
        app.state.storage = get_storage(settings)
    if not hasattr(app.state, "fetch"):
        app.state.fetch = ingest_mod.http_fetch
    # ponytail: no endpoint = no client (tests inject their own; prod always has env)
    if not hasattr(app.state, "caption_fn") and settings.azure_openai_endpoint:
        from app.captioner import Captioner, make_openai_client
        oai = make_openai_client(settings)
        app.state.oai = oai
        app.state.caption_fn = Captioner(oai, settings.azure_openai_chat_deployment).caption

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

@app.get("/healthz")
def healthz():
    return {"status": "ok"}

class CreateEventRequest(BaseModel):
    name: str

@app.post("/api/events")
def create_event_endpoint(req: CreateEventRequest,
                          x_instructor_key: str = Header(default="")):
    expected = get_settings().instructor_key
    if expected and not secrets.compare_digest(x_instructor_key, expected):
        raise HTTPException(401, "bad instructor key")
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

class QueryRequest(BaseModel):
    event_id: str
    deployment_id: str
    question: str
    screen_b64: str | None = None

def _annotate(req: QueryRequest, marker: str, deployment: str, guide: str) -> dict | None:
    url, _, label = marker.partition("|")
    url, label = url.strip(), label.strip()
    if url == "LIVE":
        image, mime = base64.b64decode(req.screen_b64), "image/png"
    else:
        if url not in guide:   # SSRF guard: only fetch URLs the guide itself references
            return None
        image, mime = app.state.fetch(url), ingest_mod._mime_for(url)
    box = annotate_mod.locate_element(app.state.oai, deployment, image, label, mime=mime)
    if box is None:
        return None
    return {"image_b64": base64.b64encode(annotate_mod.draw_box(image, box)).decode(),
            "label": label}

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
        messages=build_messages(guide, learn_results, req.question,
                                screen_b64=req.screen_b64),
        max_tokens=800,
    )
    usage = resp.usage
    # ponytail: meter only the answer completion; add the locate call's usage
    # (when the SDK reports it) if annotation cost ever matters.
    metering.record(storage, req.event_id, req.deployment_id,
                    usage.prompt_tokens, usage.completion_tokens)
    answer = resp.choices[0].message.content or ""  # content-filtered replies return None
    result = {"answer": answer, "sources": learn_results}
    lines = answer.rstrip().splitlines()
    if lines and lines[-1].startswith("ANNOTATE:"):
        result["answer"] = "\n".join(lines[:-1]).rstrip()
        try:
            annotation = _annotate(req, lines[-1][len("ANNOTATE:"):],
                                    settings.azure_openai_chat_deployment, guide)
        except Exception:
            annotation = None
        if annotation:
            result["annotation"] = annotation
    return result
