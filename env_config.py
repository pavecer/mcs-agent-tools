"""Centralized environment configuration for runtime and integrations.

The module keeps backward compatibility for legacy variable names while
exposing a canonical set of parsed values.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

_TRUE_VALUES = {"1", "true", "yes", "on"}


def _getenv(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _int_env(name: str, default: int) -> int:
    raw = _getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _bool_from_str(value: str, default: bool = False) -> bool:
    normalized = (value or "").strip().lower()
    if not normalized:
        return default
    return normalized in _TRUE_VALUES


def _bool_env(name: str, default: bool = False) -> bool:
    return _bool_from_str(_getenv(name), default=default)


def _csv_env(name: str, max_items: int | None = None) -> list[str]:
    raw = _getenv(name)
    if not raw:
        return []
    values: list[str] = []
    for item in raw.split(","):
        cleaned = item.strip()
        if cleaned and cleaned not in values:
            values.append(cleaned)
            if max_items and len(values) >= max_items:
                break
    return values


@dataclass(slots=True)
class EnvConfig:
    reflex_env: str
    api_url: str
    frontend_port: int
    backend_port: int
    users_raw: str
    openai_api_key: str
    openai_base_url: str
    openai_model: str
    openai_store_requests: bool
    mcs_enable_model_comparison: bool
    mcs_comparison_mode: str
    mcs_comparison_models: list[str]
    auth_db_dsn: str
    auth_admin_email: str
    auth_admin_password: str
    acs_email_connection_string: str
    acs_email_sender: str
    mcs_dataverse_url: str
    mcs_dataverse_token: str
    mcs_aad_tenant_id: str
    mcs_aad_client_id: str
    mcs_aad_client_secret: str
    mcs_aad_scope: str
    mcs_admin_sessions_url: str
    mcs_admin_api_token: str

    @property
    def is_prod(self) -> bool:
        return self.reflex_env == "prod"

    @property
    def has_dataverse_aad_credentials(self) -> bool:
        return bool(self.mcs_aad_tenant_id and self.mcs_aad_client_id and self.mcs_aad_client_secret)

    @property
    def has_dataverse_env_credentials(self) -> bool:
        return bool(self.mcs_dataverse_token or self.has_dataverse_aad_credentials)


def read_env_config() -> EnvConfig:
    reflex_env = _getenv("REFLEX_ENV", "dev") or "dev"
    is_prod = reflex_env == "prod"

    # OPENAI_BASE_URL is canonical; OPENAI_API_BASE remains a compatibility alias.
    openai_base_url = _getenv("OPENAI_BASE_URL") or _getenv("OPENAI_API_BASE")

    mcs_dataverse_token = _getenv("MCS_DATAVERSE_TOKEN")
    mcs_admin_api_token = _getenv("MCS_ADMIN_API_TOKEN") or mcs_dataverse_token

    return EnvConfig(
        reflex_env=reflex_env,
        api_url=_getenv("API_URL", "http://localhost:2009"),
        frontend_port=_int_env("FRONTEND_PORT", 3100 if is_prod else 3000),
        backend_port=_int_env("BACKEND_PORT", 8000),
        users_raw=_getenv("USERS"),
        openai_api_key=_getenv("OPENAI_API_KEY"),
        openai_base_url=openai_base_url,
        openai_model=_getenv("OPENAI_MODEL"),
        openai_store_requests=_bool_env("OPENAI_STORE_REQUESTS"),
        mcs_enable_model_comparison=_bool_env("MCS_ENABLE_MODEL_COMPARISON"),
        mcs_comparison_mode=(_getenv("MCS_COMPARISON_MODE", "simulated") or "simulated").lower(),
        mcs_comparison_models=_csv_env("MCS_COMPARISON_MODELS", max_items=5),
        auth_db_dsn=_getenv("AUTH_DB_DSN"),
        auth_admin_email=_getenv("AUTH_ADMIN_EMAIL").lower(),
        auth_admin_password=_getenv("AUTH_ADMIN_PASSWORD"),
        acs_email_connection_string=_getenv("ACS_EMAIL_CONNECTION_STRING"),
        acs_email_sender=_getenv("ACS_EMAIL_SENDER"),
        mcs_dataverse_url=_getenv("MCS_DATAVERSE_URL"),
        mcs_dataverse_token=mcs_dataverse_token,
        mcs_aad_tenant_id=_getenv("MCS_AAD_TENANT_ID"),
        mcs_aad_client_id=_getenv("MCS_AAD_CLIENT_ID"),
        mcs_aad_client_secret=_getenv("MCS_AAD_CLIENT_SECRET"),
        mcs_aad_scope=_getenv("MCS_AAD_SCOPE"),
        mcs_admin_sessions_url=_getenv("MCS_ADMIN_SESSIONS_URL"),
        mcs_admin_api_token=mcs_admin_api_token,
    )


def parse_env_bool(name: str, default: bool = False) -> bool:
    """Compatibility helper for call sites that still read raw env booleans."""
    return _bool_env(name, default=default)