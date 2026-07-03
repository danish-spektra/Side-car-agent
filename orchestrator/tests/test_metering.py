from app.metering import record, read_usage
from app.storage import LocalStorage

def test_record_appends_json_lines(tmp_path):
    s = LocalStorage(str(tmp_path))
    record(s, "ev1", "dep-123", 900, 150, now=1720000000.0)
    record(s, "ev1", "dep-456", 800, 100, now=1720000001.0)
    rows = read_usage(s, "ev1")
    assert rows == [
        {"event_id": "ev1", "deployment_id": "dep-123", "ts": 1720000000.0, "tokens_in": 900, "tokens_out": 150},
        {"event_id": "ev1", "deployment_id": "dep-456", "ts": 1720000001.0, "tokens_in": 800, "tokens_out": 100},
    ]

def test_read_usage_empty(tmp_path):
    assert read_usage(LocalStorage(str(tmp_path)), "ev1") == []
