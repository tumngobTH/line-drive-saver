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
    return Deps(mapping=mapping, drive=drive, line=line, root_folder_id="root1", max_file_mb=200,
                sidecar_json=True)


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

    ev = _media_event("file", "m1", 1783931412000, file_name="Q2-report.pdf")
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

    ev = _media_event("image", "m1", 1783931412000)
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

    ev = _media_event("image", "m1", 1783931412000)
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


@pytest.mark.asyncio
async def test_process_media_skips_when_already_inflight():
    from app import processor
    mapping = Mapping({"Cabc": {"folderName": "P", "folderId": "folder1"}})
    drive = MagicMock()
    line = MagicMock()
    ev = _media_event("image", "dup1", 1783931412000)

    processor._inflight.add("dup1")  # simulate a concurrent in-flight delivery
    try:
        await process_media_event(ev, _deps(mapping, drive, line))
    finally:
        processor._inflight.discard("dup1")

    drive.exists_message.assert_not_called()
    drive.upload.assert_not_called()
    line.download_content.assert_not_called()


# --- sidecar JSON -----------------------------------------------------------


def _happy_drive(existing=None):
    drive = MagicMock()
    drive.exists_message.return_value = False
    drive.list_names_in_folder.return_value = set(existing or ())
    return drive


def _happy_line(group_id="Cabc"):
    line = MagicMock()
    line.group_id_of.return_value = group_id
    line.download_content.return_value = b"bytes"
    return line


@pytest.mark.asyncio
async def test_process_media_uploads_sidecar_json_after_save():
    import json
    mapping = Mapping({"Cabc": {"folderName": "P", "folderId": "folder1"}})
    drive = _happy_drive()
    line = _happy_line()

    ev = _media_event("image", "m1", 1783931412000)
    await process_media_event(ev, _deps(mapping, drive, line))

    drive.upload.assert_called_once()
    assert drive.upload.call_args.kwargs["filename"] == "20260713_153012_image.jpg"

    drive.upload_bytes.assert_called_once()
    kw = drive.upload_bytes.call_args.kwargs
    assert kw["folder_id"] == "folder1"
    assert kw["filename"] == "20260713_153012_image.json"
    assert kw["mime_type"] == "application/json"
    payload = json.loads(kw["data"].decode("utf-8"))
    assert payload == {
        "groupId": "Cabc",
        "userId": "U1",
        "messageId": "m1",
        "sourceId": "Cabc",
        "timestamp": 1783931412000,
        "type": "image",
        "filename": "20260713_153012_image.jpg",
    }
    # The sidecar must NOT carry lineMessageId so exists_message keys on media only.
    assert "lineMessageId" not in (kw.get("app_properties") or {})
    line.push_text.assert_not_called()


@pytest.mark.asyncio
async def test_sidecar_uses_null_group_for_direct_chat():
    import json
    mapping = Mapping({"U1": {"folderName": "P", "folderId": "folder1"}})
    drive = _happy_drive()
    line = _happy_line(group_id=None)
    message = SimpleNamespace(type="image", id="m1", file_name=None)
    source = SimpleNamespace(type="user", user_id="U1")
    ev = SimpleNamespace(message=message, source=source, timestamp=1783931412000, reply_token="rt")

    await process_media_event(ev, _deps(mapping, drive, line))

    payload = json.loads(drive.upload_bytes.call_args.kwargs["data"].decode("utf-8"))
    assert payload["groupId"] is None
    assert payload["userId"] == "U1"


@pytest.mark.asyncio
async def test_sidecar_name_does_not_collide_with_json_media_file():
    mapping = Mapping({"Cabc": {"folderName": "P", "folderId": "folder1"}})
    drive = _happy_drive()
    line = _happy_line()

    ev = _media_event("file", "m1", 1783931412000, file_name="notes.json")
    await process_media_event(ev, _deps(mapping, drive, line))

    media_name = drive.upload.call_args.kwargs["filename"]
    sidecar_name = drive.upload_bytes.call_args.kwargs["filename"]
    assert media_name == "20260713_notes.json"
    assert sidecar_name.endswith(".json")
    assert sidecar_name != media_name


@pytest.mark.asyncio
async def test_sidecar_siblings_do_not_break_unique_media_name():
    # Folder already holds a media file and its sidecar from the same second.
    mapping = Mapping({"Cabc": {"folderName": "P", "folderId": "folder1"}})
    drive = _happy_drive(existing={"20260713_153012_image.jpg", "20260713_153012_image.json"})
    line = _happy_line()

    ev = _media_event("image", "m2", 1783931412000)
    await process_media_event(ev, _deps(mapping, drive, line))

    assert drive.upload.call_args.kwargs["filename"] == "20260713_153012_image_2.jpg"
    assert drive.upload_bytes.call_args.kwargs["filename"] == "20260713_153012_image_2.json"


@pytest.mark.asyncio
async def test_sidecar_failure_does_not_fail_media_save():
    mapping = Mapping({"Cabc": {"folderName": "P", "folderId": "folder1"}})
    drive = _happy_drive()
    drive.upload_bytes.side_effect = RuntimeError("sidecar boom")
    line = _happy_line()

    ev = _media_event("image", "m1", 1783931412000)
    await process_media_event(ev, _deps(mapping, drive, line))

    drive.upload.assert_called_once()
    drive.upload_bytes.assert_called_once()
    line.push_text.assert_not_called()


@pytest.mark.asyncio
async def test_no_sidecar_when_media_save_fails():
    mapping = Mapping({"Cabc": {"folderName": "P", "folderId": "folder1"}})
    drive = _happy_drive()
    drive.upload.side_effect = RuntimeError("media boom")
    line = _happy_line()

    ev = _media_event("image", "m1", 1783931412000)
    await process_media_event(ev, _deps(mapping, drive, line))

    drive.upload_bytes.assert_not_called()
    line.push_text.assert_called_once()


# --- ERROR_REPLIES opt-out -----------------------------------------------------


@pytest.mark.asyncio
async def test_error_replies_false_suppresses_notice():
    mapping = Mapping({"Cabc": {"folderName": "P", "folderId": "folder1"}})
    drive = _happy_drive()
    line = _happy_line()
    line.download_content.side_effect = RuntimeError("boom")

    deps = Deps(mapping=mapping, drive=drive, line=line, root_folder_id="root1",
                max_file_mb=200, error_replies=False)
    ev = _media_event("image", "m1", 1783931412000)
    await process_media_event(ev, deps)

    line.push_text.assert_not_called()
    drive.upload.assert_not_called()


def test_deps_error_replies_defaults_true():
    deps = _deps(Mapping({}), MagicMock(), MagicMock())
    assert deps.error_replies is True


@pytest.mark.asyncio
async def test_no_sidecar_when_flag_off_by_default():
    mapping = Mapping({"Cabc": {"folderName": "P", "folderId": "folder1"}})
    drive = _happy_drive()
    line = _happy_line()
    deps = Deps(mapping=mapping, drive=drive, line=line, root_folder_id="root1", max_file_mb=200)
    assert deps.sidecar_json is False

    await process_media_event(_media_event("image", "m1", 1783931412000), deps)

    drive.upload.assert_called_once()
    drive.upload_bytes.assert_not_called()
    line.push_text.assert_not_called()
