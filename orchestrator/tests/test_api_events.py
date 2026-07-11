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

def test_create_event_instructor_gate(client, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "instructor_key", "sekrit")
    r = client.post("/api/events", json={"name": "d"})
    assert r.status_code == 401
    r = client.post("/api/events", json={"name": "d"},
                    headers={"X-Instructor-Key": "wrong"})
    assert r.status_code == 401
    r = client.post("/api/events", json={"name": "d"},
                    headers={"X-Instructor-Key": "sekrit"})
    assert r.status_code == 200

def test_ingest_via_masterdoc_url(client):
    ev = client.post("/api/events", json={"name": "d"}).json()
    r = client.post(f"/api/events/{ev['event_id']}/ingest",
                    json={"masterdoc_url": "https://x/masterdoc.json"},
                    headers={"X-Event-Key": ev["key"]})
    assert r.status_code == 200
    assert r.json() == {"files": 1, "images": 1, "cached": False}

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

# --- preview: parse + list files WITHOUT captioning or saving anything ---

def test_preview_lists_files_without_ingesting(client, tmp_path):
    ev = client.post("/api/events", json={"name": "d"}).json()
    captions = []
    app.state.caption_fn = lambda b, mime="image/png": captions.append(1) or "cap"
    r = client.post(f"/api/events/{ev['event_id']}/preview",
                    json={"masterdoc_url": "https://x/masterdoc.json"},
                    headers={"X-Event-Key": ev["key"]})
    assert r.status_code == 200
    assert r.json() == {"name": "d", "language": "",
                        "files": ["https://x/Labs/e1.md"], "count": 1}
    assert captions == []                                   # no vision spend
    assert not app.state.storage.exists(ev["event_id"], "guide.md")  # nothing saved

def test_preview_invalid_masterdoc_422(client):
    ev = client.post("/api/events", json={"name": "d"}).json()
    app.state.fetch = lambda url: b'{"just": "some json"}'
    r = client.post(f"/api/events/{ev['event_id']}/preview",
                    json={"masterdoc_url": "https://x/masterdoc.json"},
                    headers={"X-Event-Key": ev["key"]})
    assert r.status_code == 422
    assert "not a masterdoc" in r.json()["detail"]

def test_preview_unparseable_json_422(client):
    ev = client.post("/api/events", json={"name": "d"}).json()
    app.state.fetch = lambda url: b"<html>github page, not raw json</html>"
    r = client.post(f"/api/events/{ev['event_id']}/preview",
                    json={"masterdoc_url": "https://x/masterdoc.json"},
                    headers={"X-Event-Key": ev["key"]})
    assert r.status_code == 422

def test_preview_wrong_key_401(client):
    ev = client.post("/api/events", json={"name": "d"}).json()
    r = client.post(f"/api/events/{ev['event_id']}/preview",
                    json={"masterdoc_url": "https://x/masterdoc.json"},
                    headers={"X-Event-Key": "nope"})
    assert r.status_code == 401

def test_ingest_invalid_masterdoc_422_not_500(client):
    ev = client.post("/api/events", json={"name": "d"}).json()
    app.state.fetch = lambda url: b'[]'
    r = client.post(f"/api/events/{ev['event_id']}/ingest",
                    json={"masterdoc_url": "https://x/masterdoc.json"},
                    headers={"X-Event-Key": ev["key"]})
    assert r.status_code == 422
