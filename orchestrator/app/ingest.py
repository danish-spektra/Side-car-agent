import re
from urllib.parse import urljoin

import httpx

IMG_RE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")
INJECT_RE = re.compile(r'<inject\s+key="([^"]+)"', re.IGNORECASE)

def ordered_paths(masterdoc) -> list[str]:
    doc = masterdoc[0] if isinstance(masterdoc, list) else masterdoc
    files = sorted(doc["Files"], key=lambda f: f["Order"])
    return [f["RawFilePath"] for f in files]

def extract_image_refs(md: str) -> list[str]:
    return IMG_RE.findall(md)

def resolve_ref(md_url: str, ref: str) -> str:
    return ref if ref.startswith(("http://", "https://")) else urljoin(md_url, ref)

def http_fetch(url: str) -> bytes:
    r = httpx.get(url, timeout=30, follow_redirects=True)
    r.raise_for_status()
    return r.content

import json as _json

def _mime_for(url: str) -> str:
    return "image/jpeg" if url.lower().endswith((".jpg", ".jpeg")) else "image/png"

def enrich_markdown(md: str, base_url: str, fetch, caption_fn, cache: dict) -> str:
    def repl(m):
        ref = m.group(1)
        resolved = resolve_ref(base_url, ref)
        if resolved not in cache:
            try:
                cache[resolved] = caption_fn(fetch(resolved), mime=_mime_for(resolved))
            except Exception:
                cache[resolved] = "screenshot unavailable"
        return f"{m.group(0)}\n> [Screenshot] {cache[resolved]}\n> (image: {resolved})"
    return IMG_RE.sub(repl, md)

def ingest_event(storage, fetch, caption_fn, event_id: str, masterdoc) -> dict:
    from app.storage import get_event
    cache: dict = {}
    parts = []
    for url in ordered_paths(masterdoc):
        md = fetch(url).decode("utf-8")
        parts.append(enrich_markdown(md, url, fetch, caption_fn, cache))
    guide = "\n\n---\n\n".join(parts)
    storage.save_text(event_id, "guide.md", guide)
    # inject keys recorded at ingest so the query post-filter is guide-aware (Task 1d)
    storage.save_text(event_id, "inject_keys.json",
                      _json.dumps(sorted(set(INJECT_RE.findall(guide)))))
    event = get_event(storage, event_id)
    event["status"] = "ready"
    storage.save_text(event_id, "event.json", _json.dumps(event))
    return {"files": len(parts), "images": len(cache)}
