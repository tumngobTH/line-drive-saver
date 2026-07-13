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
