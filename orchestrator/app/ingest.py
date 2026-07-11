import re
from urllib.parse import urljoin

import httpx

IMG_RE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")
INJECT_RE = re.compile(r'<inject\s+key="([^"]+)"', re.IGNORECASE)

def parse_masterdoc(masterdoc) -> dict:
    """Validate a masterdoc and summarize exactly what ingest would fetch.

    The masterdoc's Files[] is the allowlist — nothing else in the repo is
    ever fetched. Raises ValueError with an instructor-readable message.
    """
    doc = masterdoc[0] if isinstance(masterdoc, list) and masterdoc else masterdoc
    if not isinstance(doc, dict) or not isinstance(doc.get("Files"), list) or not doc["Files"]:
        raise ValueError(
            "not a masterdoc: expected JSON with a non-empty Files[] array "
            "of {RawFilePath, Order} entries")
    for f in doc["Files"]:
        url = f.get("RawFilePath") if isinstance(f, dict) else None
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            raise ValueError(f"masterdoc Files[] entry has no absolute RawFilePath URL: {f!r}")
    return {
        "name": doc.get("Name", ""),
        "language": doc.get("Language", ""),
        "files": ordered_paths(doc),
        "count": len(doc["Files"]),
    }

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

# Lab cache: one entry per lab (stable lab_id from the masterdoc's file URLs),
# versioned by a hash of the fetched md content. Same content -> reuse the
# enriched guide (zero caption spend); changed content -> re-caption and
# OVERWRITE the same entry, so old versions never accumulate.
# ponytail: an image swapped at the same URL with the md untouched is missed;
# hash image bytes too if that ever happens in practice.
LAB_CACHE = "_labcache"  # pseudo event-id; real ids are 12-hex so no collision

def ingest_event(storage, fetch, caption_fn, event_id: str, masterdoc) -> dict:
    import hashlib
    from app.storage import get_event
    urls = ordered_paths(masterdoc)
    lab_id = hashlib.sha256("\n".join(urls).encode()).hexdigest()[:16]
    pages = [fetch(url).decode("utf-8") for url in urls]  # md text is cheap; captions are not
    content_hash = hashlib.sha256("\n".join(pages).encode()).hexdigest()

    meta = None
    if storage.exists(LAB_CACHE, f"{lab_id}.meta.json"):
        meta = _json.loads(storage.load_text(LAB_CACHE, f"{lab_id}.meta.json"))
    if meta and meta["content_hash"] == content_hash:
        guide = storage.load_text(LAB_CACHE, f"{lab_id}.guide.md")
        stats = {"files": meta["files"], "images": meta["images"], "cached": True}
    else:
        cache: dict = {}
        guide = "\n\n---\n\n".join(
            enrich_markdown(md, url, fetch, caption_fn, cache)
            for url, md in zip(urls, pages))
        storage.save_text(LAB_CACHE, f"{lab_id}.guide.md", guide)
        storage.save_text(LAB_CACHE, f"{lab_id}.meta.json", _json.dumps(
            {"content_hash": content_hash, "files": len(pages), "images": len(cache)}))
        stats = {"files": len(pages), "images": len(cache), "cached": False}

    storage.save_text(event_id, "guide.md", guide)
    # inject keys recorded at ingest so the query post-filter is guide-aware (Task 1d)
    storage.save_text(event_id, "inject_keys.json",
                      _json.dumps(sorted(set(INJECT_RE.findall(guide)))))
    event = get_event(storage, event_id)
    event["status"] = "ready"
    storage.save_text(event_id, "event.json", _json.dumps(event))
    return stats
