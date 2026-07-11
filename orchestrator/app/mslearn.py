import html as _html
import re

import httpx

SEARCH_URL = "https://learn.microsoft.com/api/search"
_DROP_RE = re.compile(r"<(script|style)\b.*?</\1>", re.DOTALL | re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")

def fetch_learn_page(url: str, get_text=None, max_chars: int = 12000) -> str:
    """Fetch an MS Learn article as plain text for the LEARN_MORE deepening pass.

    Only https://learn.microsoft.com/ is ever fetched (the model picks the
    query, so this is a hard SSRF guard). Returns "" on any failure.
    """
    if not url.startswith("https://learn.microsoft.com/"):
        return ""
    try:
        if get_text is None:
            r = httpx.get(url, timeout=15, follow_redirects=True)
            r.raise_for_status()
            raw = r.text
        else:
            raw = get_text(url)
        text = _TAG_RE.sub(" ", _DROP_RE.sub(" ", raw))
        return " ".join(_html.unescape(text).split())[:max_chars]
    except Exception:
        return ""

def _default_get_json(url: str, params: dict) -> dict:
    r = httpx.get(url, params=params, timeout=10)
    r.raise_for_status()
    return r.json()

def search_learn(question: str, top: int = 3, get_json=None) -> list[dict]:
    get_json = get_json or _default_get_json
    try:
        data = get_json(SEARCH_URL, {"search": question, "locale": "en-us", "$top": top})
        return [
            {"title": r.get("title", ""), "url": r.get("url", ""),
             "summary": r.get("description") or r.get("summary") or ""}
            for r in data.get("results", [])[:top]
        ]
    except Exception:
        return []  # Q&A still works from the guide alone
