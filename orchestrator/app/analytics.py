"""Instructor analytics: what learners ask and where they pile up.

One JSONL row per answered question, aggregated on read. Same append-only
mechanism as metering; instructor key gates the read side.
"""
import json
import time

def record(storage, event_id: str, deployment_id: str, task_ref: str,
           question: str, hint_level: int, checker_flagged: bool,
           now: float | None = None) -> None:
    # `question` is instructor-visible in the portal's live view.
    # Never log the answer text or screenshots.
    row = {"ts": now if now is not None else time.time(),
           "deployment_id": deployment_id, "task_ref": task_ref,
           "question": question, "hint_level": hint_level,
           "checker_flagged": checker_flagged}
    storage.append_line(event_id, "analytics.jsonl", json.dumps(row))

def read_rows(storage, event_id: str) -> list[dict]:
    try:
        text = storage.load_text(event_id, "analytics.jsonl")
    except KeyError:
        return []
    return [json.loads(l) for l in text.splitlines() if l.strip()]

def summarize(rows: list[dict], now: float | None = None) -> dict:
    now = now if now is not None else time.time()
    by_task: dict[str, dict] = {}
    for r in rows:
        t = by_task.setdefault(r["task_ref"], {"questions": 0, "learners": set(),
                                               "max_hint_level": 0})
        t["questions"] += 1
        t["learners"].add(r["deployment_id"])
        t["max_hint_level"] = max(t["max_hint_level"], r["hint_level"])
    return {
        "total_questions": len(rows),
        "active_learners": len({r["deployment_id"] for r in rows
                                if r["ts"] > now - 900}),
        "by_task": sorted(
            ({"task_ref": ref, "questions": t["questions"],
              "distinct_learners": len(t["learners"]),
              "max_hint_level": t["max_hint_level"]}
             for ref, t in by_task.items()),
            key=lambda x: -x["questions"]),
        "recent": rows[-20:][::-1],   # newest first
    }
