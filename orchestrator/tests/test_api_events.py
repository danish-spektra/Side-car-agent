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

def test_ingest_via_masterdoc_url(client):
    ev = client.post("/api/events", json={"name": "d"}).json()
    r = client.post(f"/api/events/{ev['event_id']}/ingest",
                    json={"masterdoc_url": "https://x/masterdoc.json"},
                    headers={"X-Event-Key": ev["key"]})
    assert r.status_code == 200
    assert r.json() == {"files": 1, "images": 1}

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
