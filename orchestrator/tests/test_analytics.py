import time

import pytest
from fastapi.testclient import TestClient
from app.analytics import read_rows, record, summarize
from app.main import app
from app.storage import LocalStorage

from tests.test_api_query import FakeOAI

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

def test_query_writes_analytics_row(client):
    ev = _ready_event(client)
    client.post("/api/query",
                json={"event_id": ev["event_id"], "deployment_id": "dep-1",
                      "question": "I'm stuck on task 1"},
                headers={"X-Event-Key": ev["key"]})
    rows = read_rows(app.state.storage, ev["event_id"])
    assert len(rows) == 1
    r = rows[0]
    assert r["deployment_id"] == "dep-1"
    assert r["task_ref"] == "task1"
    assert r["question"] == "I'm stuck on task 1"
    assert r["hint_level"] == 0
    assert r["checker_flagged"] is False
    assert "answer" not in r          # never log the answer text

def test_summarize_aggregates(client):
    ev = _ready_event(client)
    s, now = app.state.storage, time.time()
    record(s, ev["event_id"], "dep-1", "task1", "q1", 0, False, now=now - 2000)
    record(s, ev["event_id"], "dep-1", "task2", "q2", 1, False, now=now - 60)
    record(s, ev["event_id"], "dep-2", "task2", "q3", 2, True, now=now - 30)
    r = client.get(f"/api/events/{ev['event_id']}/analytics")
    assert r.status_code == 200
    d = r.json()
    assert d["total_questions"] == 3
    assert d["active_learners"] == 2          # dep-1's old row is outside 15 min, recent one isn't
    assert d["by_task"][0] == {"task_ref": "task2", "questions": 2,
                               "distinct_learners": 2, "max_hint_level": 2}
    assert d["by_task"][1]["task_ref"] == "task1"
    assert [x["question"] for x in d["recent"]] == ["q3", "q2", "q1"]  # newest first

def test_recent_caps_at_20(client):
    ev = _ready_event(client)
    for i in range(25):
        record(app.state.storage, ev["event_id"], "d", "general", f"q{i}", 0, False,
               now=1000.0 + i)
    d = client.get(f"/api/events/{ev['event_id']}/analytics").json()
    assert len(d["recent"]) == 20
    assert d["recent"][0]["question"] == "q24"

def test_analytics_instructor_gate(client, monkeypatch):
    from app.config import get_settings
    ev = _ready_event(client)
    monkeypatch.setattr(get_settings(), "instructor_key", "sekrit")
    assert client.get(f"/api/events/{ev['event_id']}/analytics").status_code == 401
    assert client.get(f"/api/events/{ev['event_id']}/analytics",
                      headers={"X-Instructor-Key": "wrong"}).status_code == 401
    assert client.get(f"/api/events/{ev['event_id']}/analytics",
                      headers={"X-Instructor-Key": "sekrit"}).status_code == 200

def test_analytics_open_when_key_unset(client):
    ev = _ready_event(client)
    assert client.get(f"/api/events/{ev['event_id']}/analytics").status_code == 200

def test_analytics_unknown_event_404(client):
    assert client.get("/api/events/deadbeef/analytics").status_code == 404

def test_event_key_does_not_open_analytics(client, monkeypatch):
    from app.config import get_settings
    ev = _ready_event(client)
    monkeypatch.setattr(get_settings(), "instructor_key", "sekrit")
    r = client.get(f"/api/events/{ev['event_id']}/analytics",
                   headers={"X-Instructor-Key": ev["key"]})  # learner-held key
    assert r.status_code == 401