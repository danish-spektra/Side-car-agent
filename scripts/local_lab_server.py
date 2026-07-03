"""Serve reference-guide/ as a fake CloudLabs docs proxy for local E2E.

Usage:  python scripts/local_lab_server.py   (serves on :9000)
Then ingest with masterdoc URL: http://127.0.0.1:9000/masterdoc.json
"""
import http.server
import json
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent / "reference-guide"
PORT = 9000

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT), **kw)

    def do_GET(self):
        if self.path == "/masterdoc.json":
            files = sorted(ROOT.glob("*.md"))
            doc = [{"Name": "Local Demo Lab", "Files": [
                {"RawFilePath": f"http://127.0.0.1:{PORT}/Labs/{f.name}", "Order": i + 1}
                for i, f in enumerate(files)]}]
            body = json.dumps(doc).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._rewrite_path()
        super().do_GET()

    def do_HEAD(self):
        # ponytail: SimpleHTTPRequestHandler.do_HEAD calls send_head() directly,
        # bypassing do_GET, so the rewrite has to be applied here too.
        self._rewrite_path()
        super().do_HEAD()

    def _rewrite_path(self):
        # /Labs/x.md -> serve x.md ; /images/x.png -> Images/x.png
        self.path = re.sub(r"^/Labs/", "/", self.path)
        self.path = re.sub(r"^/images/", "/Images/", self.path, flags=re.I)

if __name__ == "__main__":
    print(f"Fake lab guide server on http://127.0.0.1:{PORT}/masterdoc.json")
    http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
