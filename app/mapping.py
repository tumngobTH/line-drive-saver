import asyncio


class Mapping:
    """In-memory groupId -> {folderName, folderId} store.

    The asyncio lock guards read-modify-write of the folder cache and the
    persisted JSON. Safe because the service runs as a single pinned instance.
    """

    def __init__(self, data: dict | None = None):
        self._data: dict[str, dict] = dict(data or {})
        self.lock = asyncio.Lock()

    def folder_name_for(self, source_id: str, fallback: str) -> str:
        entry = self._data.get(source_id)
        if entry and entry.get("folderName"):
            return entry["folderName"]
        return fallback

    def folder_id_for(self, source_id: str) -> str | None:
        entry = self._data.get(source_id)
        return entry.get("folderId") if entry else None

    def set_folder(self, source_id: str, name: str, folder_id: str) -> None:
        self._data[source_id] = {"folderName": name, "folderId": folder_id}

    def rename(self, source_id: str, new_name: str) -> None:
        entry = self._data.setdefault(source_id, {"folderName": new_name, "folderId": None})
        entry["folderName"] = new_name

    def to_dict(self) -> dict:
        return {k: dict(v) for k, v in self._data.items()}
