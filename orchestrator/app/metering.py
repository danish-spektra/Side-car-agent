import json
import time

def record(storage, event_id: str, deployment_id: str,
           tokens_in: int, tokens_out: int, tokens_cached: int = 0,
           now: float | None = None) -> None:
    row = {"event_id": event_id, "deployment_id": deployment_id,
           "ts": now if now is not None else time.time(),
           "tokens_in": tokens_in, "tokens_out": tokens_out,
           "tokens_cached": tokens_cached}
    storage.append_line(event_id, "usage.jsonl", json.dumps(row))

def cached_tokens(usage) -> int:
    """Cache hits from usage.prompt_tokens_details — absent on older models and fakes."""
    details = getattr(usage, "prompt_tokens_details", None)
    return getattr(details, "cached_tokens", 0) or 0

def read_usage(storage, event_id: str) -> list[dict]:
    try:
        text = storage.load_text(event_id, "usage.jsonl")
    except KeyError:
        return []
    return [json.loads(l) for l in text.splitlines() if l.strip()]
