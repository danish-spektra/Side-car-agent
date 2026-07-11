from fastapi.testclient import TestClient

from app.main import app
from app.storage import LocalStorage


def test_portal_served(tmp_path):
    app.state.storage = LocalStorage(str(tmp_path))
    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200
    assert "Lab Assistant" in r.text


def test_sidecar_zip_404_when_missing(tmp_path, monkeypatch):
    import app.main as main_mod
    monkeypatch.setattr(main_mod, "STATIC", tmp_path)  # empty dir -> no zip
    app.state.storage = LocalStorage(str(tmp_path))
    client = TestClient(app)
    r = client.get("/download/sidecar.zip")
    assert r.status_code == 404
    assert "not built yet" in r.json()["detail"]

def test_portal_has_preview_modal(tmp_path):
    app.state.storage = LocalStorage(str(tmp_path))
    client = TestClient(app)
    r = client.get("/")
    assert "preview-modal" in r.text          # the confirm-before-ingest popup
    assert "previewIngest" in r.text
