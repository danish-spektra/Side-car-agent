import re
from urllib.parse import urljoin

import httpx

IMG_RE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")

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
