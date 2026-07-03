import json

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from app.config import get_settings
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
