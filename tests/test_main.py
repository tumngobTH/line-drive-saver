from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

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
         patch.object(main, "_dispatch", new_callable=AsyncMock) as dispatch:
        line.parse.return_value = []
        resp = client.post("/callback", content=b"{}", headers={"X-Line-Signature": "x"})
    assert resp.status_code == 200
    dispatch.assert_called_once()


def test_callback_returns_200_when_handler_raises():
    # The real _dispatch must process events inline (await) yet never let a
    # failing handler turn the webhook into a non-200 — LINE would otherwise
    # retry the whole batch. MessageEvent is patched to `object` so a plain
    # namespace passes the isinstance filter.
    main, client = _client()
    ev = SimpleNamespace(message=SimpleNamespace(type="image"), source=SimpleNamespace())
    with patch.object(main.state, "line") as line, \
         patch.object(main, "MessageEvent", object), \
         patch.object(main, "process_media_event",
                      new=AsyncMock(side_effect=RuntimeError("boom"))) as handler:
        line.parse.return_value = [ev]
        resp = client.post("/callback", content=b"{}", headers={"X-Line-Signature": "x"})
    assert resp.status_code == 200
    handler.assert_awaited_once()
