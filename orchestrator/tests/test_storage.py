import pytest
from app.storage import LocalStorage, create_event, get_event, verify_key

@pytest.fixture
def storage(tmp_path):
    return LocalStorage(str(tmp_path))

def test_save_load_roundtrip(storage):
    storage.save_text("ev1", "guide.md", "# hello")
    assert storage.load_text("ev1", "guide.md") == "# hello"
    assert storage.exists("ev1", "guide.md")
    assert not storage.exists("ev1", "nope.md")

def test_load_missing_raises(storage):
    with pytest.raises(KeyError):
        storage.load_text("ev1", "missing.md")

def test_append_line(storage):
    storage.append_line("ev1", "usage.jsonl", '{"a":1}')
    storage.append_line("ev1", "usage.jsonl", '{"a":2}')
    assert storage.load_text("ev1", "usage.jsonl").splitlines() == ['{"a":1}', '{"a":2}']

def test_event_lifecycle(storage):
    ev = create_event(storage, "AI Foundry Workshop")
    assert ev["name"] == "AI Foundry Workshop"
    assert len(ev["key"]) >= 32
    fetched = get_event(storage, ev["event_id"])
    assert fetched["key"] == ev["key"]
    assert verify_key(storage, ev["event_id"], ev["key"])
    assert not verify_key(storage, ev["event_id"], "wrong")
    assert not verify_key(storage, "missing", ev["key"])
