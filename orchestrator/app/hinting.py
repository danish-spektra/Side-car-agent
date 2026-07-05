"""Graduated hinting: the 'guide, don't solve' boundary made structural.

A rolling per-(event, learner, task) counter picks an escalating instruction
block appended to the system prompt. Level 0 nudges, level 2+ walks the step.
"""
import json
import re

_EX_RE = re.compile(r"\b(?:exercise|ex\.?)\s*(\d+)", re.IGNORECASE)
_TASK_RE = re.compile(r"\btask\s*(\d+)", re.IGNORECASE)

def task_ref(question: str) -> str:
    """Cheap deterministic task reference: 'ex2-task3', 'task2', 'ex2' or 'general'."""
    ex = _EX_RE.search(question)
    task = _TASK_RE.search(question)
    if ex and task:
        return f"ex{ex.group(1)}-task{task.group(1)}"
    if task:
        return f"task{task.group(1)}"
    if ex:
        return f"ex{ex.group(1)}"
    return "general"

def _counts(storage, event_id: str, deployment_id: str) -> dict:
    try:
        return json.loads(storage.load_text(event_id, f"hints/{deployment_id}.json"))
    except KeyError:
        return {}

def get_hint_level(storage, event_id: str, deployment_id: str, ref: str) -> int:
    """Current 0-based hint level for this learner on this task."""
    return _counts(storage, event_id, deployment_id).get(ref, 0)

def bump(storage, event_id: str, deployment_id: str, ref: str) -> None:
    """Increment after a successful answer; stored level caps at 3."""
    counts = _counts(storage, event_id, deployment_id)
    counts[ref] = min(counts.get(ref, 0) + 1, 3)
    storage.save_text(event_id, f"hints/{deployment_id}.json", json.dumps(counts))

HINT_INSTRUCTIONS: dict[int, str] = {
    0: ("HINT LEVEL 0 (first ask on this task): give a conceptual nudge only. "
        "Name the relevant screen/blade/concept and the guide section, but do NOT "
        "give the specific setting value, button sequence, or command. End with a "
        "short guiding question."),
    1: ("HINT LEVEL 1 (second ask on this task): give a narrower pointer — the "
        "specific location (e.g. \"Networking blade > Firewalls section\") and "
        "what to look for, but still no literal values and no complete commands."),
    2: ("HINT LEVEL 2 (repeated asks on this task): give the full step reference "
        "with reasoning (\"step 4 does X because Y\"), quoting the guide's step. "
        "Still never output resolved <inject .../> values and never a "
        "copy-pasteable complete solution that skips intermediate steps."),
}

def hint_block(level: int) -> str:
    return HINT_INSTRUCTIONS[min(level, 2)]
