import base64
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from app.main import app
from app.metering import read_usage
from app.storage import LocalStorage

class FakeUsage:
    prompt_tokens = 900
    completion_tokens = 120

CANNED = "Look under Exercise 1, Task 2 — the option is in the left menu."

class FakeCompletions:
    def __init__(self, scripts=None):
        self.scripts = scripts or []
        self.calls = []

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        self.calls.append(kwargs)
        text = self.scripts.pop(0) if self.scripts else CANNED
        class Msg: content = text
        class Choice: message = Msg()
        class Resp:
            choices = [Choice()]
            usage = FakeUsage()
        return Resp()

class FakeOAI:
    def __init__(self, scripts=None):
        self.chat = type("C", (), {"completions": FakeCompletions(scripts)})()

def _tiny_png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (20, 20), "white").save(buf, "PNG")
    return buf.getvalue()

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

# --- screen companion -------------------------------------------------------

def _query(client, ev, **extra):
    return client.post("/api/query",
                       json={"event_id": ev["event_id"], "deployment_id": "d",
                             "question": "where is it?", **extra},
                       headers={"X-Event-Key": ev["key"]})

def test_annotate_marker_yields_annotation_and_stripped_answer(client):
    ev = _make_ready_event(client)
    app.state.oai = FakeOAI(scripts=[
        "It is in the left menu.\nANNOTATE: https://x/shot.png | the Save button",
        '{"found": true, "box": [2, 2, 15, 15]}',
    ])
    app.state.fetch = lambda url: _tiny_png()
    r = _query(client, ev)
    body = r.json()
    assert body["answer"] == "It is in the left menu."
    assert "ANNOTATE" not in body["answer"]
    ann = body["annotation"]
    assert ann["label"] == "the Save button"
    img = Image.open(io.BytesIO(base64.b64decode(ann["image_b64"])))
    assert img.format == "PNG"

def test_annotate_live_uses_request_screen(client):
    ev = _make_ready_event(client)
    app.state.oai = FakeOAI(scripts=[
        "You already opened it.\nANNOTATE: LIVE | the search box",
        '{"found": true, "box": [1, 1, 10, 10]}',
    ])
    def boom(url):
        raise AssertionError("fetch must not be called for LIVE")
    app.state.fetch = boom
    screen = base64.b64encode(_tiny_png()).decode()
    r = _query(client, ev, screen_b64=screen)
    body = r.json()
    assert body["annotation"]["label"] == "the search box"
    assert body["answer"] == "You already opened it."

def test_annotate_locate_failure_degrades_to_text(client):
    ev = _make_ready_event(client)
    app.state.oai = FakeOAI(scripts=[
        "Answer text.\nANNOTATE: https://x/shot.png | the thing",
        "no json in sight",
    ])
    app.state.fetch = lambda url: _tiny_png()
    r = _query(client, ev)
    body = r.json()
    assert body["answer"] == "Answer text."
    assert not body.get("annotation")

def test_screen_b64_makes_user_message_multimodal(client):
    ev = _make_ready_event(client)
    screen = base64.b64encode(_tiny_png()).decode()
    _query(client, ev, screen_b64=screen)
    user = app.state.oai.chat.completions.calls[0]["messages"][-1]
    assert user["role"] == "user"
    parts = user["content"]
    assert parts[0] == {"type": "text", "text": "where is it?"}
    assert parts[1]["image_url"]["url"] == f"data:image/png;base64,{screen}"
