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


def test_upload_bytes_passes_shared_drive_flag_and_properties():
    service = MagicMock()
    service.files().create().execute.return_value = {"id": "f1"}
    store = _store_with(service)
    out = store.upload_bytes(
        folder_id="folder1", filename="a.json", data=b"{}",
        mime_type="application/json", app_properties={"lineSidecarFor": "m1"},
    )
    assert out == "f1"
    kwargs = service.files().create.call_args.kwargs
    assert kwargs["supportsAllDrives"] is True
    assert "includeItemsFromAllDrives" not in kwargs
    assert kwargs["body"]["name"] == "a.json"
    assert kwargs["body"]["parents"] == ["folder1"]
    assert kwargs["body"]["appProperties"] == {"lineSidecarFor": "m1"}


def test_upload_tags_line_message_id():
    service = MagicMock()
    service.files().create().execute.return_value = {"id": "f1"}
    store = _store_with(service)
    store.upload(folder_id="folder1", filename="a.jpg", data=b"x",
                 mime_type="image/jpeg", message_id="m1", source_id="Cabc")
    body = service.files().create.call_args.kwargs["body"]
    assert body["appProperties"] == {"lineMessageId": "m1", "lineSourceId": "Cabc"}


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


def test_drive_calls_retry_transient_errors():
    from app.drive import DriveStore, RETRIES
    service = MagicMock()
    service.files.return_value.list.return_value.execute.return_value = {"files": [{"id": "f1"}]}
    store = DriveStore(service, "sd", "root")
    assert store.ensure_folder("P", "root") == "f1"
    service.files.return_value.list.return_value.execute.assert_called_once_with(num_retries=RETRIES)
    service.files.return_value.create.return_value.execute.return_value = {"id": "x"}
    store.upload_bytes("f1", "a.json", b"{}", "application/json")
    service.files.return_value.create.return_value.execute.assert_called_once_with(num_retries=RETRIES)
    assert RETRIES >= 1


def test_save_mapping_uses_configured_filename_when_none_given():
    service = MagicMock()
    service.files.return_value.list.return_value.execute.return_value = {"files": []}
    service.files.return_value.create.return_value.execute.return_value = {"id": "m1"}
    store = DriveStore(service, "sd", "root", mapping_filename="line-slip-mapping.json")
    store.save_mapping({"Cabc": {"folderName": "P", "folderId": "f1"}})
    body = service.files.return_value.create.call_args.kwargs["body"]
    assert body["name"] == "line-slip-mapping.json"
    assert body["parents"] == ["root"]
    # and the lookup that decided "create, not update" searched for the same name
    q = service.files.return_value.list.call_args.kwargs["q"]
    assert "line-slip-mapping.json" in q
