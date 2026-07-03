import httpx

SEARCH_URL = "https://learn.microsoft.com/api/search"

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
