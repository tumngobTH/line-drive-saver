import pytest

from app.config import Settings


def _settings(**overrides):
    # Required vars come from conftest os.environ defaults; skip any local .env.
    return Settings(_env_file=None, **overrides)


def test_error_replies_defaults_true():
    assert _settings().error_replies is True


@pytest.mark.parametrize("raw", ["false", "False", "0", "no"])
def test_error_replies_parses_false_values(raw):
    assert _settings(error_replies=raw).error_replies is False


@pytest.mark.parametrize("raw", ["true", "1", "yes"])
def test_error_replies_parses_true_values(raw):
    assert _settings(error_replies=raw).error_replies is True


def test_error_replies_reads_env(monkeypatch):
    monkeypatch.setenv("ERROR_REPLIES", "false")
    assert _settings().error_replies is False


def test_sidecar_json_defaults_false(monkeypatch):
    monkeypatch.delenv("SIDECAR_JSON", raising=False)
    assert Settings(_env_file=None).sidecar_json is False


def test_sidecar_json_env_true(monkeypatch):
    monkeypatch.setenv("SIDECAR_JSON", "true")
    assert Settings(_env_file=None).sidecar_json is True
