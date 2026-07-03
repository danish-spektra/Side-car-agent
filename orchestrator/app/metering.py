import json
import time

def record(storage, event_id: str, deployment_id: str,
           tokens_in: int, tokens_out: int, now: float | None = None) -> None:
    row = {"event_id": event_id, "deployment_id": deployment_id,
           "ts": now if now is not None else time.time(),
           "tokens_in": tokens_in, "tokens_out": tokens_out}
    storage.append_line(event_id, "usage.jsonl", json.dumps(row))

def read_usage(storage, event_id: str) -> list[dict]:
    try:
        text = storage.load_text(event_id, "usage.jsonl")
    except KeyError:
        return []
    return [json.loads(l) for l in text.splitlines() if l.strip()]
