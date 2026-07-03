from fastapi.testclient import TestClient

from app.main import app
from app.storage import LocalStorage


def test_portal_served(tmp_path):
    app.state.storage = LocalStorage(str(tmp_path))
    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200
    assert "Lab Assistant" in r.text


def test_sidecar_zip_404_when_missing(tmp_path):
    app.state.storage = LocalStorage(str(tmp_path))
    client = TestClient(app)
    r = client.get("/download/sidecar.zip")
    assert r.status_code == 404
    assert "not built yet" in r.json()["detail"]
