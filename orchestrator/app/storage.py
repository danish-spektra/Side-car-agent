import json
import secrets
import uuid
from pathlib import Path
from typing import Protocol

class Storage(Protocol):
    def save_text(self, event_id: str, name: str, text: str) -> None: ...
    def load_text(self, event_id: str, name: str) -> str: ...
    def exists(self, event_id: str, name: str) -> bool: ...
    def append_line(self, event_id: str, name: str, line: str) -> None: ...

class LocalStorage:
    def __init__(self, data_dir: str):
        self.root = Path(data_dir)

    def _path(self, event_id: str, name: str) -> Path:
        p = self.root / event_id / name
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def save_text(self, event_id, name, text):
        self._path(event_id, name).write_text(text, encoding="utf-8")

    def load_text(self, event_id, name):
        p = self._path(event_id, name)
        if not p.exists():
            raise KeyError(f"{event_id}/{name}")
        return p.read_text(encoding="utf-8")

    def exists(self, event_id, name):
        return self._path(event_id, name).exists()

    def append_line(self, event_id, name, line):
        with self._path(event_id, name).open("a", encoding="utf-8") as f:
            f.write(line + "\n")

class BlobStorage:
    """Same contract on Azure Blob. Container 'events', blob '{event_id}/{name}'."""
    def __init__(self, connection_string: str):
        from azure.storage.blob import BlobServiceClient
        from azure.core.exceptions import ResourceExistsError
        svc = BlobServiceClient.from_connection_string(connection_string)
        self.container = svc.get_container_client("events")
        try:
            self.container.create_container()
        except ResourceExistsError:
            pass  # already exists

    def _blob(self, event_id, name):
        return self.container.get_blob_client(f"{event_id}/{name}")

    def save_text(self, event_id, name, text):
        self._blob(event_id, name).upload_blob(text.encode("utf-8"), overwrite=True)

    def load_text(self, event_id, name):
        from azure.core.exceptions import ResourceNotFoundError
        try:
            return self._blob(event_id, name).download_blob().readall().decode("utf-8")
        except ResourceNotFoundError:
            raise KeyError(f"{event_id}/{name}")

    def exists(self, event_id, name):
        return self._blob(event_id, name).exists()

    def append_line(self, event_id, name, line):
        # ponytail: read-modify-write append; AppendBlob if metering volume ever matters
        try:
            current = self.load_text(event_id, name)
        except KeyError:
            current = ""
        self.save_text(event_id, name, current + line + "\n")

def get_storage(settings) -> Storage:
    if settings.storage_backend == "blob":
        return BlobStorage(settings.azure_storage_connection_string)
    return LocalStorage(settings.data_dir)

# ---- event records ----

def create_event(storage: Storage, name: str) -> dict:
    event = {
        "event_id": uuid.uuid4().hex[:12],
        "key": secrets.token_urlsafe(32),
        "name": name,
        "status": "created",
    }
    storage.save_text(event["event_id"], "event.json", json.dumps(event))
    return event

def get_event(storage: Storage, event_id: str) -> dict | None:
    try:
        return json.loads(storage.load_text(event_id, "event.json"))
    except KeyError:
        return None

def verify_key(storage: Storage, event_id: str, key: str) -> bool:
    ev = get_event(storage, event_id)
    return bool(ev) and secrets.compare_digest(ev["key"], key)
