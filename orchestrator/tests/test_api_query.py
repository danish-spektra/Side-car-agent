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
