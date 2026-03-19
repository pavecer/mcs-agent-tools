from __future__ import annotations

from env_config import parse_env_bool, read_env_config


def test_openai_base_url_prefers_canonical(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://canonical.example")
    monkeypatch.setenv("OPENAI_API_BASE", "https://legacy.example")

    env = read_env_config()

    assert env.openai_base_url == "https://canonical.example"


def test_openai_base_url_uses_legacy_alias(monkeypatch):
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.setenv("OPENAI_API_BASE", "https://legacy.example")

    env = read_env_config()

    assert env.openai_base_url == "https://legacy.example"


def test_admin_api_token_falls_back_to_dataverse_token(monkeypatch):
    monkeypatch.delenv("MCS_ADMIN_API_TOKEN", raising=False)
    monkeypatch.setenv("MCS_DATAVERSE_TOKEN", "dataverse-token")

    env = read_env_config()

    assert env.mcs_admin_api_token == "dataverse-token"


def test_dataverse_credentials_modes(monkeypatch):
    monkeypatch.delenv("MCS_DATAVERSE_TOKEN", raising=False)
    monkeypatch.setenv("MCS_AAD_TENANT_ID", "tenant")
    monkeypatch.setenv("MCS_AAD_CLIENT_ID", "client")
    monkeypatch.setenv("MCS_AAD_CLIENT_SECRET", "secret")

    env = read_env_config()

    assert env.has_dataverse_aad_credentials is True
    assert env.has_dataverse_env_credentials is True


def test_parse_env_bool_truthy(monkeypatch):
    monkeypatch.setenv("MCS_ENABLE_MODEL_COMPARISON", "YES")

    assert parse_env_bool("MCS_ENABLE_MODEL_COMPARISON") is True
