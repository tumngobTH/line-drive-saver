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
