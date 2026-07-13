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
