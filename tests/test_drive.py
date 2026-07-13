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


def _real_service():
    from googleapiclient.discovery import build
    from google.auth.credentials import AnonymousCredentials
    return build("drive", "v3", credentials=AnonymousCredentials(),
                 cache_discovery=False, static_discovery=False)


def test_write_flags_are_accepted_by_real_client():
    # Regression for the includeItemsFromAllDrives-on-create/update/get bug.
    from app import drive
    svc = _real_service()
    # These construct the underlying HttpRequest; a bad kwarg raises TypeError here.
    svc.files().create(body={"name": "x"}, fields="id", **drive._WRITE)
    svc.files().update(fileId="1", body={"name": "x"}, fields="id", **drive._WRITE)
    svc.files().get_media(fileId="1", **drive._WRITE)


def test_list_flags_are_accepted_by_real_client():
    from app import drive
    svc = _real_service()
    svc.files().list(q="x", fields="files(id)", corpora="drive",
                     driveId="0A", **drive._LIST)
