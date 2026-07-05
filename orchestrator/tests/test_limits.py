import time

import pytest
from fastapi.testclient import TestClient
from app.limits import budget_exhausted, rate_limited
from app.main import app
from app.metering import record
from app.storage import LocalStorage

from tests.test_api_query import FakeOAI

def _rows(n, deployment_id="d", ts=1000.0, tokens=(10, 5)):
    return [{"deployment_id": deployment_id, "ts": ts,
             "tokens_in": tokens[0], "tokens_out": tokens[1]} for _ in range(n)]

# --- pure functions ----------------------------------------------------------

def test_rate_limited_under_limit_returns_none():
    assert rate_limited(_rows(9, ts=1000), "d", now=1001, limit=10, window_seconds=600) is None

def test_rate_limited_at_limit_returns_retry_after():
    retry = rate_limited(_rows(10, ts=1000), "d", now=1001, limit=10, window_seconds=600)
    assert retry == 599  # oldest row ages out at 1600

def test_rate_limited_window_slides():
    rows = _rows(10, ts=1000)
    assert rate_limited(rows, "d", now=1601, limit=10, window_seconds=600) is None

def test_rate_limited_is_per_learner():
    rows = _rows(10, deployment_id="other", ts=1000)
    assert rate_limited(rows, "d", now=1001, limit=10, window_seconds=600) is None

def test_budget_exhausted():
    assert not budget_exhausted(_rows(1, tokens=(100, 50)), budget=151)
    assert budget_exhausted(_rows(1, tokens=(100, 51)), budget=151)

# --- endpoint enforcement ----------------------------------------------------

@pytest.fixture
def client(tmp_path):
    app.state.storage = LocalStorage(str(tmp_path))
    app.state.fetch = lambda url: b""
    app.state.caption_fn = lambda b, mime="image/png": "cap"
    app.state.oai = FakeOAI()
    app.state.learn_search = lambda q: []
    return TestClient(app)

def _ready_event(client):
    ev = client.post("/api/events", json={"name": "d"}).json()
    app.state.storage.save_text(ev["event_id"], "guide.md", "# Ex1\nTask 1: look left")
    return ev

def _ask(client, ev, dep="dep-1"):
    return client.post("/api/query",
                       json={"event_id": ev["event_id"], "deployment_id": dep,
                             "question": "stuck on task 1"},
                       headers={"X-Event-Key": ev["key"]})

def test_11th_question_in_window_is_429(client):
    ev = _ready_event(client)
    now = time.time()
    for _ in range(10):
        record(app.state.storage, ev["event_id"], "dep-1", 10, 5, now=now)
    r = _ask(client, ev)
    assert r.status_code == 429
    body = r.json()
    assert body["error"] == "rate_limited"
    assert 0 < body["retry_after_seconds"] <= 600

def test_question_after_window_slides_is_200(client):
    ev = _ready_event(client)
    stale = time.time() - 601
    for _ in range(10):
        record(app.state.storage, ev["event_id"], "dep-1", 10, 5, now=stale)
    assert _ask(client, ev).status_code == 200

def test_other_learner_not_rate_limited(client):
    ev = _ready_event(client)
    now = time.time()
    for _ in range(10):
        record(app.state.storage, ev["event_id"], "dep-1", 10, 5, now=now)
    assert _ask(client, ev, dep="dep-2").status_code == 200

def test_budget_exhaustion_is_402(client):
    ev = _ready_event(client)
    record(app.state.storage, ev["event_id"], "dep-1", 1_999_000, 1_000,
           now=time.time() - 9_999)  # old row: budget counts, rate window doesn't
    r = _ask(client, ev)
    assert r.status_code == 402
    assert r.json()["error"] == "event_budget_exhausted"
