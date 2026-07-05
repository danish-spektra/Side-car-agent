import base64
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from app.main import app
from app.metering import read_usage
from app.storage import LocalStorage

class FakeTokenDetails:
    cached_tokens = 512

class FakeUsage:
    prompt_tokens = 900
    completion_tokens = 120
    prompt_tokens_details = FakeTokenDetails()

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
    app.state.storage.save_text(
        ev["event_id"], "guide.md",
        "# Exercise 1\nTask 2: click the left menu\n(image: https://x/shot.png)")
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
    # answer + checker calls are both metered into one row
    assert rows[0]["tokens_in"] == 1800 and rows[0]["tokens_out"] == 240

def test_query_guide_in_system_prompt(client):
    ev = _make_ready_event(client)
    client.post("/api/query",
                json={"event_id": ev["event_id"], "deployment_id": "d", "question": "q"},
                headers={"X-Event-Key": ev["key"]})
    sent = app.state.oai.chat.completions.calls[0]["messages"]  # answer call (checker follows)
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
        "POINT",  # checker verdict
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
        "POINT",  # checker verdict
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
        "POINT",  # checker verdict
        "no json in sight",
    ])
    app.state.fetch = lambda url: _tiny_png()
    r = _query(client, ev)
    body = r.json()
    assert body["answer"] == "Answer text."
    assert not body.get("annotation")

def test_annotate_url_not_in_guide_is_ignored_and_not_fetched(client):
    ev = _make_ready_event(client)
    app.state.oai = FakeOAI(scripts=[
        "Answer text.\nANNOTATE: https://evil.example/steal.png | the thing",
        "POINT",  # checker verdict
    ])
    def boom(url):
        raise AssertionError("must not fetch a URL that is not in the guide")
    app.state.fetch = boom
    r = _query(client, ev)
    body = r.json()
    assert body["answer"] == "Answer text."
    assert not body.get("annotation")

# --- prompt caching (v2) -----------------------------------------------------

def test_metering_records_cached_tokens(client):
    ev = _make_ready_event(client)
    _query(client, ev)
    rows = read_usage(app.state.storage, ev["event_id"])
    assert rows[0]["tokens_cached"] == 2 * 512  # answer + checker calls

def test_metering_survives_usage_without_details(client):
    ev = _make_ready_event(client)

    class BareUsage:  # older models / SDKs: no prompt_tokens_details at all
        prompt_tokens = 10
        completion_tokens = 5
    orig = FakeCompletions.create
    def create_bare(self, **kwargs):
        resp = orig(self, **kwargs)
        resp.usage = BareUsage()
        return resp
    app.state.oai.chat.completions.create = create_bare.__get__(
        app.state.oai.chat.completions)
    r = _query(client, ev)
    assert r.status_code == 200
    rows = read_usage(app.state.storage, ev["event_id"])
    assert rows[0]["tokens_cached"] == 0

def test_system_message_is_cacheable_prefix(client):
    """Static rules first, guide before any per-request (learn/hint) text —
    byte-identical prefix across learners is what makes Azure's cache hit."""
    ev = _make_ready_event(client)
    _query(client, ev)
    sys = app.state.oai.chat.completions.calls[0]["messages"][0]["content"]
    assert sys.startswith("You are the CloudLabs Lab Assistant")
    guide_at = sys.index("click the left menu")
    assert guide_at < sys.index("https://learn.microsoft.com/d")  # learn results after guide
    assert guide_at < sys.index("HINT LEVEL")                      # hint block after guide

# --- graduated hinting + checker (v2) ---------------------------------------

def test_hint_blocks_escalate_for_repeated_asks(client):
    ev = _make_ready_event(client)
    for _ in range(3):
        r = client.post("/api/query",
                        json={"event_id": ev["event_id"], "deployment_id": "dep-1",
                              "question": "I'm stuck on task 2"},
                        headers={"X-Event-Key": ev["key"]})
        assert r.status_code == 200
    calls = app.state.oai.chat.completions.calls
    # answer calls are 0, 2, 4 (a checker call follows each answer)
    assert "HINT LEVEL 0" in calls[0]["messages"][0]["content"]
    assert "HINT LEVEL 1" in calls[2]["messages"][0]["content"]
    assert "HINT LEVEL 2" in calls[4]["messages"][0]["content"]

def test_hint_levels_are_per_task_ref(client):
    ev = _make_ready_event(client)
    for q in ["I'm stuck on task 2", "now help with task 3"]:
        client.post("/api/query",
                    json={"event_id": ev["event_id"], "deployment_id": "dep-1",
                          "question": q},
                    headers={"X-Event-Key": ev["key"]})
    calls = app.state.oai.chat.completions.calls
    assert "HINT LEVEL 0" in calls[0]["messages"][0]["content"]
    assert "HINT LEVEL 0" in calls[2]["messages"][0]["content"]  # new task_ref resets

def test_checker_perform_triggers_one_regeneration(client):
    ev = _make_ready_event(client)
    app.state.oai = FakeOAI(scripts=[
        "Run `az storage account create -n labsa123`.",   # draft that solves
        "PERFORM",                                          # checker rejects
        "Look at Exercise 1, Task 2 — what makes a name unique?",  # regen
        "POINT",                                            # checker accepts
    ])
    r = _query(client, ev)
    assert r.status_code == 200
    assert "Exercise 1" in r.json()["answer"]
    calls = app.state.oai.chat.completions.calls
    assert len(calls) == 4                                  # never loops past one regen
    assert any("Rewrite it to point" in str(m.get("content"))
               for m in calls[2]["messages"])
    rows = read_usage(app.state.storage, ev["event_id"])
    assert rows[0]["tokens_in"] == 4 * 900                  # all calls metered
    assert rows[0]["tokens_out"] == 4 * 120

def test_checker_double_fail_returns_regenerated_answer(client):
    ev = _make_ready_event(client)
    app.state.oai = FakeOAI(scripts=[
        "Full solution v1.", "PERFORM",
        "Full solution v2.", "PERFORM",
    ])
    r = _query(client, ev)
    assert r.status_code == 200
    assert r.json()["answer"] == "Full solution v2."        # returned anyway, just logged
    assert len(app.state.oai.chat.completions.calls) == 4   # no second regen

def test_inject_tags_never_reach_learner(client):
    ev = _make_ready_event(client)
    app.state.oai = FakeOAI(scripts=[
        'Name it storage<inject key="Deployment ID"/> and continue.',
        "POINT",
    ])
    r = _query(client, ev)
    a = r.json()["answer"]
    assert "<inject" not in a
    assert "Environment Details" in a

def test_screen_b64_makes_user_message_multimodal(client):
    ev = _make_ready_event(client)
    screen = base64.b64encode(_tiny_png()).decode()
    _query(client, ev, screen_b64=screen)
    user = app.state.oai.chat.completions.calls[0]["messages"][-1]
    assert user["role"] == "user"
    parts = user["content"]
    assert parts[0] == {"type": "text", "text": "where is it?"}
    assert parts[1]["image_url"]["url"] == f"data:image/png;base64,{screen}"
