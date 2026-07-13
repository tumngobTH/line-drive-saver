# LINE → Google Drive File Saver Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A LINE bot that saves every file shared in a group chat to Google Drive, one folder per chat, each file renamed with a `yyyymmdd` date prefix.

**Architecture:** FastAPI app on Cloud Run (single always-on instance). The `/callback` webhook verifies LINE's signature, returns `200` immediately, then processes each media message in a background task: resolve the chat's Drive folder, dedupe against LINE retries, download the content from LINE, build the filename, and upload to a Shared Drive via a service account. A small JSON file in the Shared Drive holds the `groupId → {folderName, folderId}` mapping.

**Tech Stack:** Python 3.12, FastAPI + uvicorn, `line-bot-sdk` v3, `google-api-python-client` + `google-auth`, `pydantic-settings`, pytest + httpx.

**Service account:** `service-account@n8nproject-493006.iam.gserviceaccount.com` — must be granted **Content-Manager** on the target Shared Drive. Its JSON key path goes in `GOOGLE_APPLICATION_CREDENTIALS`.

**Spec:** `docs/superpowers/specs/2026-07-13-line-drive-saver-design.md`

---

## File Structure

| File | Responsibility |
|---|---|
| `requirements.txt` | Pinned dependencies |
| `.env.example` | Template of required env vars (real `.env` git-ignored) |
| `app/__init__.py` | Marks package |
| `app/config.py` | Typed settings from env via `pydantic-settings` |
| `app/naming.py` | Pure filename building: date prefix, per-type, sanitize, collision suffix |
| `app/mapping.py` | In-memory `groupId → {folderName, folderId}` store + resolution + asyncio lock |
| `app/drive.py` | Google Drive wrapper: ensure folder, list names, dedupe query, upload, rename, load/save mapping JSON |
| `app/line_client.py` | LINE wrapper: parse+verify events, download content, group-summary name, push message |
| `app/commands.py` | Parse and handle `/folder`, `/help` text commands |
| `app/processor.py` | Orchestrates one media event end-to-end (ties naming+mapping+drive+line) |
| `app/main.py` | FastAPI app, `/callback` webhook, `/` health, background dispatch, startup wiring |
| `tests/…` | Unit tests per module (LINE + Drive mocked) |
| `Dockerfile` | Container build for Cloud Run |
| `README.md` | Setup + deploy instructions |
| `CLAUDE.md` | Project instructions (house pattern) |

---

## Task 0: Project scaffold

**Files:**
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `app/__init__.py`
- Create: `app/config.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `pytest.ini`

- [ ] **Step 1: Write `requirements.txt`**

```
fastapi==0.115.6
uvicorn[standard]==0.34.0
line-bot-sdk==3.14.4
google-api-python-client==2.156.0
google-auth==2.37.0
pydantic-settings==2.7.1
```

- [ ] **Step 2: Write `requirements-dev.txt`**

```
-r requirements.txt
pytest==8.3.4
pytest-asyncio==0.25.2
httpx==0.28.1
```

- [ ] **Step 3: Write `.env.example`**

```
LINE_CHANNEL_SECRET=your_channel_secret
LINE_CHANNEL_ACCESS_TOKEN=your_long_lived_access_token
GOOGLE_APPLICATION_CREDENTIALS=./service-account.json
SHARED_DRIVE_ID=0A...shared_drive_id
ROOT_FOLDER_ID=1...folder_in_shared_drive_for_chats_and_mapping
MAX_FILE_MB=200
MAPPING_FILENAME=line-drive-mapping.json
```

- [ ] **Step 4: Write `app/__init__.py` and `tests/__init__.py`** (both empty files)

- [ ] **Step 5: Write `pytest.ini`**

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
```

- [ ] **Step 6: Write `app/config.py`**

```python
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    line_channel_secret: str
    line_channel_access_token: str
    google_application_credentials: str
    shared_drive_id: str
    root_folder_id: str
    max_file_mb: int = 200
    mapping_filename: str = "line-drive-mapping.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 7: Write `tests/conftest.py`** (env so `get_settings()` never hits a real `.env`)

```python
import os

os.environ.setdefault("LINE_CHANNEL_SECRET", "test_secret")
os.environ.setdefault("LINE_CHANNEL_ACCESS_TOKEN", "test_token")
os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", "/tmp/fake-sa.json")
os.environ.setdefault("SHARED_DRIVE_ID", "0Atest")
os.environ.setdefault("ROOT_FOLDER_ID", "1roottest")
```

- [ ] **Step 8: Create venv and install**

Run:
```bash
cd "C:/Users/kimra/CodingProject/line-drive-saver"
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt
```
Expected: installs succeed.

- [ ] **Step 9: Commit**

```bash
git add requirements.txt requirements-dev.txt .env.example app/ tests/ pytest.ini
git commit -m "chore: project scaffold and config"
```

---

## Task 1: Filename building (`app/naming.py`)

Pure, no I/O — fully TDD.

**Files:**
- Create: `app/naming.py`
- Test: `tests/test_naming.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_naming.py
from app import naming


def test_file_keeps_original_name_with_date_prefix():
    # 2026-07-13 15:30:12 Asia/Bangkok == 1768293012000 ms
    ts = 1768293012000
    assert naming.build_filename("file", ts, original_name="Q2-report.pdf") == "20260713_Q2-report.pdf"


def test_image_uses_date_time_type():
    ts = 1768293012000
    assert naming.build_filename("image", ts) == "20260713_153012_image.jpg"


def test_video_and_audio_extensions():
    ts = 1768293012000
    assert naming.build_filename("video", ts) == "20260713_153012_video.mp4"
    assert naming.build_filename("audio", ts) == "20260713_153012_audio.m4a"


def test_sanitize_strips_path_and_control_chars_but_keeps_thai():
    ts = 1768293012000
    out = naming.build_filename("file", ts, original_name="../ใบเสร็จ\t/x.pdf")
    assert out == "20260713_..ใบเสร็จx.pdf"


def test_resolve_unique_appends_suffix_before_extension():
    existing = {"20260713_a.pdf", "20260713_a_2.pdf"}
    assert naming.resolve_unique("20260713_a.pdf", existing) == "20260713_a_3.pdf"


def test_resolve_unique_returns_name_when_free():
    assert naming.resolve_unique("20260713_a.pdf", set()) == "20260713_a.pdf"
```

- [ ] **Step 2: Run to verify fail**

Run: `.venv/Scripts/python -m pytest tests/test_naming.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.naming'`.

- [ ] **Step 3: Write `app/naming.py`**

```python
import re
from datetime import datetime, timedelta, timezone

BANGKOK = timezone(timedelta(hours=7))

EXT_BY_TYPE = {"image": "jpg", "video": "mp4", "audio": "m4a"}

# Strip path separators and ASCII control chars; keep everything else (incl. Thai).
_ILLEGAL = re.compile(r"[\\/\x00-\x1f]")


def _sanitize(name: str) -> str:
    cleaned = _ILLEGAL.sub("", name).strip()
    return cleaned[:200] or "file"


def date_parts(ts_ms: int) -> tuple[str, str]:
    dt = datetime.fromtimestamp(ts_ms / 1000, BANGKOK)
    return dt.strftime("%Y%m%d"), dt.strftime("%H%M%S")


def build_filename(
    msg_type: str,
    ts_ms: int,
    original_name: str | None = None,
    ext: str | None = None,
) -> str:
    ymd, hms = date_parts(ts_ms)
    if msg_type == "file" and original_name:
        return f"{ymd}_{_sanitize(original_name)}"
    extension = ext or EXT_BY_TYPE.get(msg_type, "bin")
    return f"{ymd}_{hms}_{msg_type}.{extension}"


def _with_suffix(filename: str, n: int) -> str:
    stem, dot, ext = filename.rpartition(".")
    if dot:
        return f"{stem}_{n}.{ext}"
    return f"{filename}_{n}"


def resolve_unique(name: str, existing) -> str:
    if name not in existing:
        return name
    n = 2
    while _with_suffix(name, n) in existing:
        n += 1
    return _with_suffix(name, n)
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python -m pytest tests/test_naming.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add app/naming.py tests/test_naming.py
git commit -m "feat: filename building with date prefix, sanitize, collision suffix"
```

---

## Task 2: Chat→folder mapping (`app/mapping.py`)

**Files:**
- Create: `app/mapping.py`
- Test: `tests/test_mapping.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_mapping.py
from app.mapping import Mapping


def test_resolve_name_prefers_mapping_entry():
    m = Mapping({"Cabc": {"folderName": "ProjectX", "folderId": "f1"}})
    assert m.folder_name_for("Cabc", fallback="Cabc") == "ProjectX"


def test_resolve_name_uses_fallback_when_absent():
    m = Mapping({})
    assert m.folder_name_for("Cxyz", fallback="Cxyz") == "Cxyz"


def test_folder_id_for_returns_none_when_absent():
    m = Mapping({})
    assert m.folder_id_for("Cxyz") is None


def test_set_and_get_folder():
    m = Mapping({})
    m.set_folder("Cabc", "ProjectX", "f1")
    assert m.folder_id_for("Cabc") == "f1"
    assert m.folder_name_for("Cabc", fallback="x") == "ProjectX"


def test_rename_keeps_folder_id():
    m = Mapping({"Cabc": {"folderName": "Old", "folderId": "f1"}})
    m.rename("Cabc", "New")
    assert m.folder_name_for("Cabc", fallback="x") == "New"
    assert m.folder_id_for("Cabc") == "f1"


def test_roundtrip_dict():
    data = {"Cabc": {"folderName": "P", "folderId": "f1"}}
    assert Mapping(data).to_dict() == data
```

- [ ] **Step 2: Run to verify fail**

Run: `.venv/Scripts/python -m pytest tests/test_mapping.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.mapping'`.

- [ ] **Step 3: Write `app/mapping.py`**

```python
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
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python -m pytest tests/test_mapping.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add app/mapping.py tests/test_mapping.py
git commit -m "feat: chat-to-folder mapping store with rename"
```

---

## Task 3: Google Drive wrapper (`app/drive.py`)

Wraps a Drive `service` object (injected for testability). All calls set the Shared-Drive flags.

**Files:**
- Create: `app/drive.py`
- Test: `tests/test_drive.py`

- [ ] **Step 1: Write the failing tests** (mock the Drive `service`)

```python
# tests/test_drive.py
import json
from unittest.mock import MagicMock

from app.drive import DriveStore


def _store_with(service):
    return DriveStore(service=service, shared_drive_id="0Ad", root_folder_id="root1")


def test_ensure_folder_returns_existing_id():
    service = MagicMock()
    service.files().list().execute.return_value = {"files": [{"id": "existing"}]}
    store = _store_with(service)
    assert store.ensure_folder("ProjectX", "root1") == "existing"
    service.files().create.assert_not_called()


def test_ensure_folder_creates_when_missing():
    service = MagicMock()
    service.files().list().execute.return_value = {"files": []}
    service.files().create().execute.return_value = {"id": "new1"}
    store = _store_with(service)
    assert store.ensure_folder("ProjectX", "root1") == "new1"


def test_exists_message_true_when_query_returns_hit():
    service = MagicMock()
    service.files().list().execute.return_value = {"files": [{"id": "x"}]}
    store = _store_with(service)
    assert store.exists_message("folder1", "msg123") is True


def test_exists_message_false_when_empty():
    service = MagicMock()
    service.files().list().execute.return_value = {"files": []}
    store = _store_with(service)
    assert store.exists_message("folder1", "msg123") is False


def test_list_names_returns_set():
    service = MagicMock()
    service.files().list().execute.return_value = {
        "files": [{"name": "a.pdf"}, {"name": "b.pdf"}]
    }
    store = _store_with(service)
    assert store.list_names_in_folder("folder1") == {"a.pdf", "b.pdf"}


def test_load_mapping_empty_when_no_file():
    service = MagicMock()
    service.files().list().execute.return_value = {"files": []}
    store = _store_with(service)
    assert store.load_mapping() == {}
```

- [ ] **Step 2: Run to verify fail**

Run: `.venv/Scripts/python -m pytest tests/test_drive.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.drive'`.

- [ ] **Step 3: Write `app/drive.py`**

```python
import io
import json

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload, MediaIoBaseDownload

SCOPES = ["https://www.googleapis.com/auth/drive"]
FOLDER_MIME = "application/vnd.google-apps.folder"

# Flags required for every call that touches a Shared Drive.
_SHARED = {"supportsAllDrives": True, "includeItemsFromAllDrives": True}


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
            **_SHARED,
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
            **_SHARED,
        ).execute()
        return created["id"]

    def rename_folder(self, folder_id: str, new_name: str) -> None:
        self.service.files().update(
            fileId=folder_id, body={"name": new_name}, fields="id", **_SHARED
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
            **_SHARED,
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
        request = self.service.files().get_media(fileId=file_id, **_SHARED)
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
                fileId=file_id, media_body=media, fields="id", **_SHARED
            ).execute()
        else:
            self.service.files().create(
                body={"name": filename, "parents": [self.root_folder_id]},
                media_body=media,
                fields="id",
                **_SHARED,
            ).execute()
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python -m pytest tests/test_drive.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add app/drive.py tests/test_drive.py
git commit -m "feat: Drive wrapper (ensure folder, dedupe, upload, mapping persistence)"
```

---

## Task 4: Command parsing (`app/commands.py`)

**Files:**
- Create: `app/commands.py`
- Test: `tests/test_commands.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_commands.py
from app.commands import HELP_TEXT, parse_command


def test_parse_non_command_returns_none():
    assert parse_command("hello world") is None


def test_parse_folder_command_with_arg():
    assert parse_command("/folder ProjectX") == ("folder", "ProjectX")


def test_parse_folder_command_trims_and_keeps_spaces_in_name():
    assert parse_command("/folder  My Project  ") == ("folder", "My Project")


def test_parse_help_command_no_arg():
    assert parse_command("/help") == ("help", "")


def test_parse_is_case_insensitive_on_verb():
    assert parse_command("/HELP") == ("help", "")


def test_help_text_is_nonempty():
    assert HELP_TEXT.strip()
```

- [ ] **Step 2: Run to verify fail**

Run: `.venv/Scripts/python -m pytest tests/test_commands.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.commands'`.

- [ ] **Step 3: Write `app/commands.py`**

```python
HELP_TEXT = (
    "คำสั่งที่ใช้ได้:\n"
    "/folder <ชื่อ> — ตั้งชื่อโฟลเดอร์ของแชตนี้ใน Drive\n"
    "/help — แสดงคำสั่ง\n"
    "ไฟล์ที่แชร์ในแชตนี้จะถูกบันทึกลง Google Drive อัตโนมัติ"
)


def parse_command(text: str) -> tuple[str, str] | None:
    """Return (verb, arg) for a '/command', else None."""
    if not text or not text.startswith("/"):
        return None
    parts = text[1:].split(maxsplit=1)
    if not parts:
        return None
    verb = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""
    return verb, arg
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python -m pytest tests/test_commands.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add app/commands.py tests/test_commands.py
git commit -m "feat: slash-command parsing (/folder, /help)"
```

---

## Task 5: LINE client wrapper (`app/line_client.py`)

Wraps `line-bot-sdk` v3. `source_id_of` is pure and tested; the API methods are thin pass-throughs verified with mocks.

**Files:**
- Create: `app/line_client.py`
- Test: `tests/test_line_client.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_line_client.py
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.line_client import LineClient, source_id_of


def test_source_id_of_group():
    src = SimpleNamespace(type="group", group_id="Cabc", user_id="U1")
    assert source_id_of(src) == "Cabc"


def test_source_id_of_room():
    src = SimpleNamespace(type="room", room_id="Rxyz", user_id="U1")
    assert source_id_of(src) == "Rxyz"


def test_source_id_of_user():
    src = SimpleNamespace(type="user", user_id="U1")
    assert source_id_of(src) == "U1"


def test_group_id_of_returns_none_for_user_source():
    src = SimpleNamespace(type="user", user_id="U1")
    client = LineClient(channel_secret="s", channel_access_token="t")
    assert client.group_id_of(src) is None


def test_download_content_reads_blob_bytes():
    client = LineClient(channel_secret="s", channel_access_token="t")
    fake_blob = MagicMock()
    fake_blob.get_message_content.return_value = b"filebytes"
    client._blob_api = lambda: fake_blob
    assert client.download_content("msg1") == b"filebytes"
```

- [ ] **Step 2: Run to verify fail**

Run: `.venv/Scripts/python -m pytest tests/test_line_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.line_client'`.

- [ ] **Step 3: Write `app/line_client.py`**

```python
from linebot.v3 import WebhookParser
from linebot.v3.exceptions import InvalidSignatureError  # noqa: F401 (re-exported)
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    MessagingApiBlob,
    PushMessageRequest,
    TextMessage,
)


def source_id_of(source) -> str:
    """The stable id we key folders by: group > room > user."""
    if source.type == "group":
        return source.group_id
    if source.type == "room":
        return source.room_id
    return source.user_id


class LineClient:
    def __init__(self, channel_secret: str, channel_access_token: str):
        self._parser = WebhookParser(channel_secret)
        self._config = Configuration(access_token=channel_access_token)

    def parse(self, body: str, signature: str):
        """Verify signature and return events. Raises InvalidSignatureError."""
        return self._parser.parse(body, signature)

    def group_id_of(self, source) -> str | None:
        if source.type == "group":
            return source.group_id
        return None

    def _blob_api(self):
        return MessagingApiBlob(ApiClient(self._config))

    def _messaging_api(self):
        return MessagingApi(ApiClient(self._config))

    def download_content(self, message_id: str) -> bytes:
        return self._blob_api().get_message_content(message_id)

    def get_group_summary_name(self, group_id: str) -> str | None:
        try:
            summary = self._messaging_api().get_group_summary(group_id)
            return summary.group_name
        except Exception:
            return None

    def push_text(self, to: str, text: str) -> None:
        self._messaging_api().push_message(
            PushMessageRequest(to=to, messages=[TextMessage(text=text)])
        )
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python -m pytest tests/test_line_client.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add app/line_client.py tests/test_line_client.py
git commit -m "feat: LINE client wrapper (parse, download, group name, push)"
```

---

## Task 6: Event processor (`app/processor.py`)

Orchestrates one media event and one command event, wiring naming + mapping + drive + line. Everything is injected so it is fully mockable.

**Files:**
- Create: `app/processor.py`
- Test: `tests/test_processor.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_processor.py
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.mapping import Mapping
from app.processor import Deps, handle_command_event, process_media_event

MIME_BY_TYPE = {"image": "image/jpeg", "file": "application/octet-stream"}


def _media_event(msg_type, message_id, ts, source_id="Cabc", file_name=None):
    message = SimpleNamespace(type=msg_type, id=message_id, file_name=file_name)
    source = SimpleNamespace(type="group", group_id=source_id, user_id="U1")
    return SimpleNamespace(message=message, source=source, timestamp=ts, reply_token="rt")


def _deps(mapping, drive, line):
    return Deps(mapping=mapping, drive=drive, line=line, root_folder_id="root1", max_file_mb=200)


@pytest.mark.asyncio
async def test_process_media_creates_folder_and_uploads():
    mapping = Mapping({})
    drive = MagicMock()
    drive.ensure_folder.return_value = "folder1"
    drive.exists_message.return_value = False
    drive.list_names_in_folder.return_value = set()
    line = MagicMock()
    line.source_id_of = None
    line.group_id_of.return_value = "Cabc"
    line.get_group_summary_name.return_value = "ProjectX"
    line.download_content.return_value = b"bytes"

    ev = _media_event("file", "m1", 1768293012000, file_name="Q2-report.pdf")
    await process_media_event(ev, _deps(mapping, drive, line))

    drive.ensure_folder.assert_called_once_with("ProjectX", "root1")
    args, kwargs = drive.upload.call_args
    assert kwargs["filename"] == "20260713_Q2-report.pdf"
    assert kwargs["message_id"] == "m1"
    assert mapping.folder_id_for("Cabc") == "folder1"


@pytest.mark.asyncio
async def test_process_media_skips_duplicate():
    mapping = Mapping({"Cabc": {"folderName": "P", "folderId": "folder1"}})
    drive = MagicMock()
    drive.exists_message.return_value = True
    line = MagicMock()

    ev = _media_event("image", "m1", 1768293012000)
    await process_media_event(ev, _deps(mapping, drive, line))

    drive.upload.assert_not_called()
    line.download_content.assert_not_called()


@pytest.mark.asyncio
async def test_process_media_pushes_error_on_failure():
    mapping = Mapping({"Cabc": {"folderName": "P", "folderId": "folder1"}})
    drive = MagicMock()
    drive.exists_message.return_value = False
    drive.list_names_in_folder.return_value = set()
    line = MagicMock()
    line.download_content.side_effect = RuntimeError("boom")

    ev = _media_event("image", "m1", 1768293012000)
    await process_media_event(ev, _deps(mapping, drive, line))

    line.push_text.assert_called_once()
    assert "Cabc" == line.push_text.call_args.args[0]


@pytest.mark.asyncio
async def test_handle_folder_command_renames_and_confirms():
    mapping = Mapping({"Cabc": {"folderName": "Old", "folderId": "folder1"}})
    drive = MagicMock()
    line = MagicMock()
    source = SimpleNamespace(type="group", group_id="Cabc", user_id="U1")

    await handle_command_event("folder", "New", source, _deps(mapping, drive, line))

    drive.rename_folder.assert_called_once_with("folder1", "New")
    assert mapping.folder_name_for("Cabc", fallback="x") == "New"
    line.push_text.assert_called_once()
```

- [ ] **Step 2: Run to verify fail**

Run: `.venv/Scripts/python -m pytest tests/test_processor.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.processor'`.

- [ ] **Step 3: Write `app/processor.py`**

```python
import logging
from dataclasses import dataclass

from app import naming
from app.commands import HELP_TEXT
from app.line_client import source_id_of
from app.mapping import Mapping

logger = logging.getLogger(__name__)

MEDIA_TYPES = {"image", "file", "video", "audio"}

MIME_BY_TYPE = {
    "image": "image/jpeg",
    "video": "video/mp4",
    "audio": "audio/m4a",
    "file": "application/octet-stream",
}


@dataclass
class Deps:
    mapping: Mapping
    drive: object
    line: object
    root_folder_id: str
    max_file_mb: int = 200


async def _ensure_folder(source, deps: Deps) -> str:
    source_id = source_id_of(source)
    async with deps.mapping.lock:
        folder_id = deps.mapping.folder_id_for(source_id)
        if folder_id:
            return folder_id
        group_id = deps.line.group_id_of(source)
        summary = deps.line.get_group_summary_name(group_id) if group_id else None
        name = deps.mapping.folder_name_for(source_id, fallback=summary or source_id)
        folder_id = deps.drive.ensure_folder(name, deps.root_folder_id)
        deps.mapping.set_folder(source_id, name, folder_id)
        deps.drive.save_mapping(deps.mapping.to_dict())
        return folder_id


async def process_media_event(event, deps: Deps) -> None:
    source = event.source
    source_id = source_id_of(source)
    message = event.message
    msg_type = message.type
    message_id = message.id
    try:
        folder_id = await _ensure_folder(source, deps)
        if deps.drive.exists_message(folder_id, message_id):
            logger.info("Skip duplicate %s in %s", message_id, source_id)
            return
        original = getattr(message, "file_name", None)
        base = naming.build_filename(msg_type, event.timestamp, original_name=original)
        existing = deps.drive.list_names_in_folder(folder_id)
        filename = naming.resolve_unique(base, existing)
        data = deps.line.download_content(message_id)
        deps.drive.upload(
            folder_id=folder_id,
            filename=filename,
            data=data,
            mime_type=MIME_BY_TYPE.get(msg_type, "application/octet-stream"),
            message_id=message_id,
            source_id=source_id,
        )
        logger.info("Saved %s as %s", message_id, filename)
    except Exception:  # noqa: BLE001 — report to chat, never crash the worker
        logger.exception("Failed to save %s", message_id)
        try:
            deps.line.push_text(source_id, "⚠️ บันทึกไฟล์ลง Drive ไม่สำเร็จ กรุณาลองส่งใหม่อีกครั้ง")
        except Exception:
            logger.exception("Failed to push error notice")


async def handle_command_event(verb: str, arg: str, source, deps: Deps) -> None:
    source_id = source_id_of(source)
    if verb == "help":
        deps.line.push_text(source_id, HELP_TEXT)
        return
    if verb == "folder":
        if not arg:
            deps.line.push_text(source_id, "ใช้: /folder <ชื่อโฟลเดอร์>")
            return
        async with deps.mapping.lock:
            deps.mapping.rename(source_id, arg)
            folder_id = deps.mapping.folder_id_for(source_id)
            if folder_id:
                deps.drive.rename_folder(folder_id, arg)
            deps.drive.save_mapping(deps.mapping.to_dict())
        deps.line.push_text(source_id, f"เปลี่ยนชื่อโฟลเดอร์เป็น: {arg} ✅")
        return
    deps.line.push_text(source_id, "ไม่รู้จักคำสั่งนี้ ลอง /help")
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python -m pytest tests/test_processor.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add app/processor.py tests/test_processor.py
git commit -m "feat: event processor orchestrating media save and commands"
```

---

## Task 7: FastAPI app + webhook (`app/main.py`)

**Files:**
- Create: `app/main.py`
- Test: `tests/test_main.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_main.py
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


def _client():
    from app import main
    return main, TestClient(main.app)


def test_health_ok():
    _main, client = _client()
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_callback_rejects_bad_signature():
    from linebot.v3.exceptions import InvalidSignatureError
    main, client = _client()
    with patch.object(main.state, "line") as line:
        line.parse.side_effect = InvalidSignatureError("bad")
        resp = client.post("/callback", content=b"{}", headers={"X-Line-Signature": "x"})
    assert resp.status_code == 400


def test_callback_accepts_and_returns_200():
    main, client = _client()
    with patch.object(main.state, "line") as line, \
         patch.object(main, "_dispatch") as dispatch:
        line.parse.return_value = []
        resp = client.post("/callback", content=b"{}", headers={"X-Line-Signature": "x"})
    assert resp.status_code == 200
    dispatch.assert_called_once()
```

- [ ] **Step 2: Run to verify fail**

Run: `.venv/Scripts/python -m pytest tests/test_main.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.main'`.

- [ ] **Step 3: Write `app/main.py`**

```python
import asyncio
import logging

from fastapi import FastAPI, Header, HTTPException, Request
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import MessageEvent

from app.commands import parse_command
from app.config import get_settings
from app.drive import DriveStore, build_service
from app.line_client import LineClient
from app.mapping import Mapping
from app.processor import MEDIA_TYPES, Deps, handle_command_event, process_media_event

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="line-drive-saver")


class _State:
    line: LineClient
    deps: Deps


state = _State()


@app.on_event("startup")
def _startup() -> None:
    settings = get_settings()
    state.line = LineClient(settings.line_channel_secret, settings.line_channel_access_token)
    service = build_service(settings.google_application_credentials)
    drive = DriveStore(service, settings.shared_drive_id, settings.root_folder_id)
    mapping = Mapping(drive.load_mapping(settings.mapping_filename))
    state.deps = Deps(
        mapping=mapping,
        drive=drive,
        line=state.line,
        root_folder_id=settings.root_folder_id,
        max_file_mb=settings.max_file_mb,
    )
    logger.info("Startup complete; %d chats mapped", len(mapping.to_dict()))


@app.get("/")
def health() -> dict:
    return {"status": "ok"}


def _dispatch(events) -> None:
    for event in events:
        if not isinstance(event, MessageEvent):
            continue
        msg_type = event.message.type
        if msg_type in MEDIA_TYPES:
            asyncio.create_task(process_media_event(event, state.deps))
        elif msg_type == "text":
            parsed = parse_command(event.message.text)
            if parsed:
                verb, arg = parsed
                asyncio.create_task(
                    handle_command_event(verb, arg, event.source, state.deps)
                )


@app.post("/callback")
async def callback(request: Request, x_line_signature: str = Header(default="")):
    body = (await request.body()).decode("utf-8")
    try:
        events = state.line.parse(body, x_line_signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="invalid signature")
    _dispatch(events)
    return {"status": "ok"}
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python -m pytest tests/test_main.py -v`
Expected: PASS (3 passed). Note: the health/dispatch tests patch `state.line`, so no real Drive/LINE calls occur.

- [ ] **Step 5: Run the whole suite**

Run: `.venv/Scripts/python -m pytest -v`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add app/main.py tests/test_main.py
git commit -m "feat: FastAPI webhook with signature verify and background dispatch"
```

---

## Task 8: Containerization + docs

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`
- Create: `README.md`
- Create: `CLAUDE.md`

- [ ] **Step 1: Write `Dockerfile`**

```dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

ENV PORT=8080
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
```

- [ ] **Step 2: Write `.dockerignore`**

```
.venv/
tests/
docs/
__pycache__/
*.pyc
.env
service-account*.json
.git/
```

- [ ] **Step 3: Write `README.md`**

````markdown
# line-drive-saver

Saves every file shared in a LINE group chat to Google Drive — one folder per
chat, each file renamed with a `yyyymmdd` date prefix.

## Setup

### 1. LINE Messaging API channel
- Create a Messaging API channel in the LINE Developers console.
- Copy the **Channel secret** and issue a long-lived **Channel access token**.
- Disable auto-reply; enable **Use webhook**.
- Add the bot to your group(s), and enable "Allow bot to join group chats".

### 2. Service account + Shared Drive
- Service account: `service-account@n8nproject-493006.iam.gserviceaccount.com`.
- Ensure the **Google Drive API** is enabled in project `n8nproject-493006`.
- Create (or pick) a **Shared Drive**. Add the service-account email as a
  **Content manager** member.
- Inside that Shared Drive, create a root folder for this bot. Note its folder id
  (`ROOT_FOLDER_ID`) and the Shared Drive id (`SHARED_DRIVE_ID`).
- Download the service-account JSON key and save it as `service-account.json`
  (git-ignored). If no key file exists, create one in the GCP console →
  IAM & Admin → Service Accounts → Keys → Add key.

### 3. Env
Copy `.env.example` to `.env` and fill in every value.

## Run locally
```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000
# expose to LINE:
ngrok http 8000    # put https://<id>.ngrok.app/callback in the channel webhook URL
```

## Test
```bash
.venv/Scripts/python -m pytest -v
```

## Deploy (Cloud Run)
```bash
gcloud run deploy line-drive-saver \
  --source . \
  --region asia-southeast1 \
  --min-instances 1 --max-instances 1 \
  --no-cpu-throttling \
  --set-env-vars SHARED_DRIVE_ID=...,ROOT_FOLDER_ID=...,MAPPING_FILENAME=line-drive-mapping.json \
  --set-secrets LINE_CHANNEL_SECRET=line-secret:latest,LINE_CHANNEL_ACCESS_TOKEN=line-token:latest,GOOGLE_APPLICATION_CREDENTIALS=/secrets/sa.json:...
```
Then set the channel webhook URL to `https://<cloud-run-url>/callback`.

> `--no-cpu-throttling` keeps the CPU allocated so background upload tasks finish
> after the 200 response. `--min/max-instances 1` pins to one instance so the
> mapping JSON never has concurrent writers.
````

- [ ] **Step 4: Write `CLAUDE.md`**

```markdown
# line-drive-saver

## Overview
LINE bot that saves files shared in group chats to Google Drive, one folder per
chat, filenames prefixed with the share date (yyyymmdd). See
`docs/superpowers/specs/2026-07-13-line-drive-saver-design.md`.

## Tech Stack
- FastAPI + line-bot-sdk v3 (Python 3.12)
- Google Drive via service account → Shared Drive
- Deploy: Cloud Run (asia-southeast1, min=max=1, CPU always allocated)

## Project Structure
- `app/main.py` — FastAPI webhook + dispatch
- `app/processor.py` — orchestrates one event (save / command)
- `app/drive.py` — Drive wrapper (Shared Drive flags on every call)
- `app/line_client.py` — LINE SDK wrapper
- `app/mapping.py` — groupId → folder mapping (persisted as JSON in Drive)
- `app/naming.py` — filename builder
- `app/commands.py` — /folder, /help

## Rules
- Never commit `.env` or `service-account*.json`.
- No new packages without approval.
- All calls that touch Drive must pass supportsAllDrives / driveId flags.
- Bot replies only on error or command; silent on successful save.
- Reply/notice language: Thai.

## Testing
`.venv/Scripts/python -m pytest -v`
```

- [ ] **Step 5: Verify build (optional, if Docker available)**

Run: `docker build -t line-drive-saver .`
Expected: build succeeds.

- [ ] **Step 6: Commit**

```bash
git add Dockerfile .dockerignore README.md CLAUDE.md
git commit -m "docs: Dockerfile, README setup/deploy, project CLAUDE.md"
```

---

## Manual verification (post-implementation)

1. Fill `.env`, place `service-account.json`, grant the SA Content-Manager on the Shared Drive.
2. `uvicorn app.main:app --reload --port 8000` + `ngrok http 8000`; set the webhook URL.
3. In a test LINE group, share: a photo, a PDF, a short video, a voice message.
4. Confirm a folder appears in the Shared Drive named after the group, containing
   `20260713_*.jpg`, `20260713_<name>.pdf`, `20260713_*.mp4`, `20260713_*.m4a`.
5. Send `/folder TestProject`; confirm the folder is renamed and the bot replies.
6. Re-share the same photo; confirm no duplicate is created (dedupe).
7. Deploy to Cloud Run; repeat step 3 once against the deployed URL.

---

## Self-Review notes

- **Spec coverage:** all four media types (Task 6/7 MEDIA_TYPES), one-folder-per-chat
  (Task 3/6), friendly names + `/folder` (Task 4/6), date-prefix naming (Task 1),
  dedupe via appProperties (Task 3/6), silent-on-success/error-reply (Task 6),
  JSON mapping in Drive (Task 3), single-instance deploy (Task 8) — all mapped.
- **Type consistency:** `Deps`, `DriveStore` method names, `source_id_of`, and
  `Mapping` methods are used identically across Tasks 2–7.
- **No placeholders:** every code step contains complete code; no TBD/TODO.
