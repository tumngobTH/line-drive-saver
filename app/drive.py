import io
import json

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload, MediaIoBaseDownload

SCOPES = ["https://www.googleapis.com/auth/drive"]
FOLDER_MIME = "application/vnd.google-apps.folder"

# supportsAllDrives is valid on ALL file operations; includeItemsFromAllDrives
# is ONLY valid on files.list. Splitting them avoids a TypeError on
# create / update / get_media.
_WRITE = {"supportsAllDrives": True}
_LIST = {"supportsAllDrives": True, "includeItemsFromAllDrives": True}


def build_service(credentials_path: str):
    creds = service_account.Credentials.from_service_account_file(
        credentials_path, scopes=SCOPES
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


class DriveStore:
    def __init__(self, service, shared_drive_id: str, root_folder_id: str):
        self.service = service
        self.shared_drive_id = shared_drive_id
        self.root_folder_id = root_folder_id

    def _list_kwargs(self, q: str, fields: str) -> dict:
        return {
            "q": q,
            "fields": fields,
            "corpora": "drive",
            "driveId": self.shared_drive_id,
            **_LIST,
        }

    def ensure_folder(self, name: str, parent_id: str) -> str:
        q = (
            f"name = '{_escape(name)}' and mimeType = '{FOLDER_MIME}' "
            f"and '{parent_id}' in parents and trashed = false"
        )
        resp = self.service.files().list(
            **self._list_kwargs(q, "files(id)")
        ).execute()
        files = resp.get("files", [])
        if files:
            return files[0]["id"]
        created = self.service.files().create(
            body={"name": name, "mimeType": FOLDER_MIME, "parents": [parent_id]},
            fields="id",
            **_WRITE,
        ).execute()
        return created["id"]

    def rename_folder(self, folder_id: str, new_name: str) -> None:
        self.service.files().update(
            fileId=folder_id, body={"name": new_name}, fields="id", **_WRITE
        ).execute()

    def list_names_in_folder(self, folder_id: str) -> set[str]:
        q = f"'{folder_id}' in parents and trashed = false"
        resp = self.service.files().list(
            **self._list_kwargs(q, "files(name)")
        ).execute()
        return {f["name"] for f in resp.get("files", [])}

    def exists_message(self, folder_id: str, message_id: str) -> bool:
        q = (
            f"'{folder_id}' in parents and trashed = false "
            f"and appProperties has {{ key='lineMessageId' and value='{_escape(message_id)}' }}"
        )
        resp = self.service.files().list(
            **self._list_kwargs(q, "files(id)")
        ).execute()
        return bool(resp.get("files"))

    def upload(
        self,
        folder_id: str,
        filename: str,
        data: bytes,
        mime_type: str,
        message_id: str,
        source_id: str,
    ) -> str:
        media = MediaInMemoryUpload(data, mimetype=mime_type, resumable=True)
        created = self.service.files().create(
            body={
                "name": filename,
                "parents": [folder_id],
                "appProperties": {"lineMessageId": message_id, "lineSourceId": source_id},
            },
            media_body=media,
            fields="id",
            **_WRITE,
        ).execute()
        return created["id"]

    def _find_mapping_file_id(self, filename: str) -> str | None:
        q = (
            f"name = '{_escape(filename)}' and '{self.root_folder_id}' in parents "
            f"and trashed = false"
        )
        resp = self.service.files().list(
            **self._list_kwargs(q, "files(id)")
        ).execute()
        files = resp.get("files", [])
        return files[0]["id"] if files else None

    def load_mapping(self, filename: str = "line-drive-mapping.json") -> dict:
        file_id = self._find_mapping_file_id(filename)
        if not file_id:
            return {}
        request = self.service.files().get_media(fileId=file_id, **_WRITE)
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return json.loads(buffer.getvalue().decode("utf-8") or "{}")

    def save_mapping(self, data: dict, filename: str = "line-drive-mapping.json") -> None:
        payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        media = MediaInMemoryUpload(payload, mimetype="application/json")
        file_id = self._find_mapping_file_id(filename)
        if file_id:
            self.service.files().update(
                fileId=file_id, media_body=media, fields="id", **_WRITE
            ).execute()
        else:
            self.service.files().create(
                body={"name": filename, "parents": [self.root_folder_id]},
                media_body=media,
                fields="id",
                **_WRITE,
            ).execute()
