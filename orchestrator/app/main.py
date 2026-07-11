import base64
import json
import logging
import re
import secrets
import time
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

from app.config import get_settings
from app import analytics
from app import annotate as annotate_mod
from app import checker as checker_mod
from app import hinting
from app import ingest as ingest_mod
from app import limits
from app import metering
from app.mslearn import fetch_learn_page, search_learn
from app.query import build_messages
from app.storage import create_event, get_event, get_storage, verify_key

app = FastAPI(title="CloudLabs Lab Assistant Orchestrator")
log = logging.getLogger(__name__)

# Task 1d: code guarantee — inject tags never reach the learner, prompt or not.
INJECT_TAG_RE = re.compile(r"<inject\b[^>]*>?", re.IGNORECASE)
INJECT_REMINDER = "(use the value from your Environment Details tab)"

def _strip_inject(answer: str) -> str:
    return INJECT_TAG_RE.sub(INJECT_REMINDER, answer)

REGEN_LINE = ("Your previous draft solved the step outright. Rewrite it to "
              "point and explain without giving the complete solution.")

DEEPEN_LINE = ("FULL MS LEARN ARTICLE (fetched for your LEARN_MORE query — "
               "answer the learner's question from it, following all the "
               "rules; do not output LEARN_MORE again):\n\n")

def _strip_learn_more(answer: str) -> str:
    return "\n".join(l for l in answer.rstrip().splitlines()
                     if not l.startswith("LEARN_MORE:")).rstrip()

@app.on_event("startup")
def _wire():
    settings = get_settings()
    if not hasattr(app.state, "storage"):
        app.state.storage = get_storage(settings)
    if not hasattr(app.state, "fetch"):
        app.state.fetch = ingest_mod.http_fetch
    if not hasattr(app.state, "caption_fn"):
        if settings.azure_openai_endpoint:
            from app.captioner import Captioner, make_openai_client
            oai = make_openai_client(settings)
            app.state.oai = oai
            app.state.caption_fn = Captioner(oai, settings.azure_openai_chat_deployment).caption
        else:
            # no Azure OpenAI env: ingest still works, images get a placeholder caption
            app.state.caption_fn = lambda b, mime="image/png": "screenshot (captioning disabled — no AZURE_OPENAI_ENDPOINT)"

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

def _load_masterdoc(req: IngestRequest):
    """Fetch + validate the masterdoc; 422 with a readable message on anything wrong."""
    masterdoc = req.masterdoc
    if masterdoc is None:
        if not req.masterdoc_url:
            raise HTTPException(422, "masterdoc or masterdoc_url required")
        try:
            masterdoc = json.loads(app.state.fetch(req.masterdoc_url).decode("utf-8"))
        except Exception as e:
            raise HTTPException(422, f"could not fetch/parse masterdoc URL: {e}")
    try:
        ingest_mod.parse_masterdoc(masterdoc)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return masterdoc

@app.post("/api/events/{event_id}/preview")
def preview_endpoint(event_id: str, req: IngestRequest,
                     x_event_key: str = Header(default="")):
    # dry run: shows exactly which files ingest would fetch — nothing is saved
    _check_event(event_id, x_event_key)
    return ingest_mod.parse_masterdoc(_load_masterdoc(req))

@app.post("/api/events/{event_id}/ingest")
def ingest_endpoint(event_id: str, req: IngestRequest,
                    x_event_key: str = Header(default="")):
    _check_event(event_id, x_event_key)
    masterdoc = _load_masterdoc(req)
    return ingest_mod.ingest_event(app.state.storage, app.state.fetch,
                                   app.state.caption_fn, event_id, masterdoc)

@app.get("/api/events/{event_id}/analytics")
def analytics_endpoint(event_id: str, x_instructor_key: str = Header(default="")):
    # instructor key, NOT the event key — the event key sits on every learner VM
    expected = get_settings().instructor_key
    if expected and not secrets.compare_digest(x_instructor_key, expected):
        raise HTTPException(401, "bad instructor key")
    if get_event(app.state.storage, event_id) is None:
        raise HTTPException(404, "unknown event")
    return analytics.summarize(analytics.read_rows(app.state.storage, event_id))

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
    settings = get_settings()
    # abuse limits gate BEFORE any LLM spend (event key sits on hostile VMs)
    usage_rows = metering.read_usage(storage, req.event_id)
    retry_after = limits.rate_limited(usage_rows, req.deployment_id, time.time(),
                                      settings.rate_limit_questions,
                                      settings.rate_limit_window_seconds)
    if retry_after is not None:
        return JSONResponse(status_code=429, content={
            "error": "rate_limited", "retry_after_seconds": retry_after})
    if limits.budget_exhausted(usage_rows, settings.event_token_budget):
        return JSONResponse(status_code=402, content={
            "error": "event_budget_exhausted"})
    learn_search = getattr(app.state, "learn_search", search_learn)
    learn_results = learn_search(req.question)
    ref = hinting.task_ref(req.question)
    level = hinting.get_hint_level(storage, req.event_id, req.deployment_id, ref)
    messages = build_messages(guide, learn_results, req.question,
                              screen_b64=req.screen_b64,
                              hint_block=hinting.hint_block(level))
    resp = app.state.oai.chat.completions.create(
        model=settings.azure_openai_chat_deployment,
        messages=messages,
        max_completion_tokens=settings.answer_max_completion_tokens,
    )
    usages = [resp.usage]
    answer = resp.choices[0].message.content or ""  # content-filtered replies return None
    # LEARN_MORE deepening: guide + excerpts weren't enough — fetch the full
    # MS Learn article ONCE and re-answer with it. Marker never reaches learner.
    lines = answer.rstrip().splitlines()
    if lines and lines[-1].startswith("LEARN_MORE:"):
        learn_query = lines[-1][len("LEARN_MORE:"):].strip()
        learn_fetch = getattr(app.state, "learn_fetch", fetch_learn_page)
        deep_results = learn_search(learn_query) or learn_results
        article = ""
        for res in deep_results:
            article = learn_fetch(res["url"])
            if article:
                learn_results = deep_results  # surface what we actually used
                break
        if article:
            resp = app.state.oai.chat.completions.create(
                model=settings.azure_openai_chat_deployment,
                messages=messages + [
                    {"role": "assistant", "content": answer},
                    {"role": "system", "content": DEEPEN_LINE + article}],
                max_completion_tokens=settings.answer_max_completion_tokens,
            )
            usages.append(resp.usage)
            answer = resp.choices[0].message.content or ""
        answer = _strip_learn_more(answer)
    # Task 1c: cheap second pass — did the draft PERFORM instead of POINT?
    checker_dep = (settings.azure_openai_checker_deployment
                   or settings.azure_openai_chat_deployment)
    ok, check_usage = checker_mod.check_answer(
        app.state.oai, checker_dep, req.question, answer)
    usages.append(check_usage)
    checker_flagged = False
    if not ok:  # regenerate ONCE, never loop
        resp = app.state.oai.chat.completions.create(
            model=settings.azure_openai_chat_deployment,
            messages=messages + [{"role": "assistant", "content": answer},
                                 {"role": "system", "content": REGEN_LINE}],
            max_completion_tokens=settings.answer_max_completion_tokens,
        )
        usages.append(resp.usage)
        answer = resp.choices[0].message.content or ""
        ok, check_usage = checker_mod.check_answer(
            app.state.oai, checker_dep, req.question, answer)
        usages.append(check_usage)
        checker_flagged = not ok
        if checker_flagged:
            log.warning("checker still flags PERFORM after regeneration: "
                        "event=%s deployment=%s", req.event_id, req.deployment_id)
    hinting.bump(storage, req.event_id, req.deployment_id, ref)
    # ponytail: meter all completions in this request (answer + checker + regen);
    # the annotate locate call stays unmetered until the SDK reports its usage.
    metering.record(storage, req.event_id, req.deployment_id,
                    sum(u.prompt_tokens for u in usages),
                    sum(u.completion_tokens for u in usages),
                    tokens_cached=sum(metering.cached_tokens(u) for u in usages))
    analytics.record(storage, req.event_id, req.deployment_id, ref,
                     req.question, level, checker_flagged)
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
    result["answer"] = _strip_inject(result["answer"])
    return result
