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
