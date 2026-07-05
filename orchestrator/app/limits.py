"""Abuse limits computed from the existing usage.jsonl rows — no new storage.

The event key ships in plaintext config.json on hostile VMs, so /api/query
must gate, not just record.
"""
import math

def rate_limited(rows: list[dict], deployment_id: str, now: float,
                 limit: int, window_seconds: int) -> int | None:
    """Sliding window per learner. Returns retry_after_seconds, or None if OK."""
    # ponytail: full usage.jsonl scan per request; switch to a cached counter if volume ever matters
    recent = [r["ts"] for r in rows
              if r["deployment_id"] == deployment_id and r["ts"] > now - window_seconds]
    if len(recent) < limit:
        return None
    return max(1, math.ceil(min(recent) + window_seconds - now))

def budget_exhausted(rows: list[dict], budget: int) -> bool:
    """Per-event token budget across all learners."""
    return sum(r["tokens_in"] + r["tokens_out"] for r in rows) >= budget
