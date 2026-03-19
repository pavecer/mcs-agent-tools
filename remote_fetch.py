"""Remote fetch helpers for environment-backed agent analysis.

This module supports two retrieval paths:
- Power Platform CLI (pac)
- Dataverse Web API

The public entry point is ``fetch_agent_data``.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from env_config import read_env_config


_GUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_GUID_SEARCH_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


class RemoteFetchError(RuntimeError):
    """Raised when remote retrieval cannot continue."""


@dataclass(slots=True)
class FetchedAgentData:
    """Normalized payload returned by remote fetch providers."""

    agent_id: str
    agent_name: str
    bot_content_yaml: str
    provider: str
    transcript_activities: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class _AgentRef:
    agent_id: str
    name: str


@dataclass(slots=True)
class DataverseAuthConfig:
    """Optional Dataverse auth overrides.

    When omitted, env vars are used.
    """

    token: str | None = None
    tenant_id: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    scope: str | None = None


def fetch_agent_data(
    *,
    environment: str,
    agent: str,
    provider: str = "auto",
    include_transcripts: bool = True,
    transcript_days: int = 7,
    dataverse_url: str | None = None,
) -> FetchedAgentData:
    """Fetch latest bot content (and optional transcripts) from a remote environment."""
    mode = (provider or "auto").strip().lower()
    if mode not in {"auto", "pac", "api", "dataverse"}:
        raise RemoteFetchError(f"Unsupported provider: {provider}")

    errors: list[str] = []

    if mode in {"auto", "pac"}:
        try:
            return _fetch_with_pac(
                environment=environment,
                agent=agent,
                include_transcripts=include_transcripts,
                transcript_days=transcript_days,
                dataverse_url=dataverse_url,
            )
        except RemoteFetchError as exc:
            if mode == "pac":
                raise
            errors.append(f"pac provider failed: {exc}")

    if mode in {"auto", "api", "dataverse"}:
        try:
            return _fetch_with_dataverse(
                environment=environment,
                agent=agent,
                include_transcripts=include_transcripts,
                transcript_days=transcript_days,
                dataverse_url=dataverse_url,
            )
        except RemoteFetchError as exc:
            errors.append(f"dataverse provider failed: {exc}")

    joined = " | ".join(errors) if errors else "No provider could fetch agent content"
    raise RemoteFetchError(joined)


def fetch_transcript_by_id(
    *,
    environment: str,
    transcript_id: str,
    dataverse_url: str | None = None,
    auth: DataverseAuthConfig | None = None,
) -> tuple[list[dict], dict]:
    """Fetch one transcript row by ID and return normalized activities + metadata."""
    if not transcript_id.strip():
        raise RemoteFetchError("Transcript ID is required.")

    base_url = _resolve_dataverse_url(environment=environment, dataverse_url=dataverse_url)
    headers = _build_dataverse_headers(base_url=base_url, auth=auth)
    row, table_name = _find_transcript_row_by_id(base_url=base_url, headers=headers, transcript_id=transcript_id)
    activities = _rows_to_activities([row])
    if not activities:
        raise RemoteFetchError("Transcript row was found, but no recognizable text field was available for analysis.")

    metadata = {
        "transcript_source": "dataverse",
        "transcript_table": table_name,
        "transcript_id": transcript_id.strip(),
        "transcript_rows": 1,
    }
    metadata.update(_extract_transcript_row_metadata(row))
    return activities, metadata


def check_dataverse_connection(
    *,
    environment: str,
    dataverse_url: str | None = None,
    auth: DataverseAuthConfig | None = None,
) -> dict:
    """Validate Dataverse connectivity and authentication."""
    base_url = _resolve_dataverse_url(environment=environment, dataverse_url=dataverse_url)
    headers = _build_dataverse_headers(base_url=base_url, auth=auth)
    payload = _dataverse_get(f"{base_url}/api/data/v9.2/WhoAmI()", headers)
    if not isinstance(payload, dict):
        raise RemoteFetchError("Unexpected response from Dataverse WhoAmI endpoint.")
    return {
        "dataverse_url": base_url,
        "user_id": str(payload.get("UserId", "")),
        "business_unit_id": str(payload.get("BusinessUnitId", "")),
        "organization_id": str(payload.get("OrganizationId", "")),
    }


def authenticate_dataverse(
    *,
    environment: str,
    dataverse_url: str | None = None,
    auth: DataverseAuthConfig | None = None,
) -> dict:
    """Acquire a Dataverse access token and return resolved connection context.

    This function intentionally does not depend on pac authentication.
    """
    base_url = _resolve_dataverse_url(environment=environment, dataverse_url=dataverse_url)
    token = _resolve_dataverse_token(base_url=base_url, auth=auth)
    return {
        "dataverse_url": base_url,
        "access_token": token,
        "token_source": "manual" if auth else "environment",
    }


def has_dataverse_env_credentials() -> bool:
    """Return True when environment-based Dataverse credentials are configured."""
    return read_env_config().has_dataverse_env_credentials


def begin_device_code_auth(
    *,
    environment: str,
    dataverse_url: str | None,
    tenant_id: str,
    client_id: str,
    scope: str | None = None,
) -> dict:
    """Start OAuth device-code flow for Dataverse delegated authentication."""
    base_url = _resolve_dataverse_url(environment=environment, dataverse_url=dataverse_url)
    tenant = (tenant_id or "").strip()
    client = (client_id or "").strip()
    if not tenant or not client:
        raise RemoteFetchError("Tenant ID and Client ID are required for device-code authentication.")

    resolved_scope = (scope or "").strip() or f"{base_url}/user_impersonation offline_access openid profile"
    form = urlencode({"client_id": client, "scope": resolved_scope}).encode("utf-8")
    url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/devicecode"

    req = Request(url, data=form, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except OSError as exc:
        raise RemoteFetchError(f"Failed to start device-code authentication: {exc}") from exc

    if not isinstance(payload, dict) or not payload.get("device_code"):
        raise RemoteFetchError("Device-code response is missing required fields.")

    return {
        "dataverse_url": base_url,
        "tenant_id": tenant,
        "client_id": client,
        "scope": resolved_scope,
        "device_code": str(payload.get("device_code", "")),
        "user_code": str(payload.get("user_code", "")),
        "verification_uri": str(payload.get("verification_uri", payload.get("verification_url", ""))),
        "verification_uri_complete": str(payload.get("verification_uri_complete", "")),
        "message": str(payload.get("message", "")),
        "expires_in": int(payload.get("expires_in", 0) or 0),
        "interval": int(payload.get("interval", 5) or 5),
    }


def complete_device_code_auth(*, tenant_id: str, client_id: str, device_code: str) -> dict:
    """Complete OAuth device-code flow (single poll attempt)."""
    tenant = (tenant_id or "").strip()
    client = (client_id or "").strip()
    code = (device_code or "").strip()
    if not tenant or not client or not code:
        raise RemoteFetchError("Tenant ID, Client ID and device code are required to complete authentication.")

    form = urlencode(
        {
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "client_id": client,
            "device_code": code,
        }
    ).encode("utf-8")
    url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"

    req = Request(url, data=form, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="ignore")
        try:
            payload = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            payload = {}
        err = str(payload.get("error", "")).strip().lower()
        if err in {"authorization_pending", "slow_down"}:
            return {
                "status": "pending",
                "message": str(
                    payload.get("error_description", "Authorization still pending. Complete sign-in and retry.")
                ),
            }
        if err == "expired_token":
            raise RemoteFetchError("Device code expired. Start authentication again.") from exc
        detail = str(payload.get("error_description", raw or exc.reason))
        raise RemoteFetchError(f"Device-code authentication failed: {detail}") from exc
    except OSError as exc:
        raise RemoteFetchError(f"Failed to complete device-code authentication: {exc}") from exc

    token = str(payload.get("access_token", "")).strip()
    if not token:
        raise RemoteFetchError("Token response did not include access_token.")

    return {
        "status": "success",
        "access_token": token,
        "expires_in": int(payload.get("expires_in", 0) or 0),
        "token_type": str(payload.get("token_type", "Bearer")),
    }


def _fetch_with_pac(
    *,
    environment: str,
    agent: str,
    include_transcripts: bool,
    transcript_days: int,
    dataverse_url: str | None,
) -> FetchedAgentData:
    _ensure_pac_available()
    agent_ref = _resolve_agent_with_pac(environment=environment, agent=agent)
    yaml_text = _extract_template_with_pac(environment=environment, agent_id=agent_ref.agent_id)

    warnings: list[str] = []
    activities: list[dict] = []
    metadata: dict = {"source": "pac"}

    if include_transcripts:
        try:
            activities, tx_meta, tx_warnings = _fetch_transcripts(
                environment=environment,
                agent_id=agent_ref.agent_id,
                transcript_days=transcript_days,
                dataverse_url=dataverse_url,
            )
            metadata.update(tx_meta)
            warnings.extend(tx_warnings)
        except RemoteFetchError as exc:
            warnings.append(
                "Transcript fetch skipped: "
                f"{exc}. Provide local transcript JSON manually to enrich conversation analytics."
            )

    return FetchedAgentData(
        agent_id=agent_ref.agent_id,
        agent_name=agent_ref.name,
        bot_content_yaml=yaml_text,
        provider="pac",
        transcript_activities=activities,
        metadata=metadata,
        warnings=warnings,
    )


def _fetch_with_dataverse(
    *,
    environment: str,
    agent: str,
    include_transcripts: bool,
    transcript_days: int,
    dataverse_url: str | None,
) -> FetchedAgentData:
    base_url = _resolve_dataverse_url(environment=environment, dataverse_url=dataverse_url)
    headers = _build_dataverse_headers(base_url=base_url, auth=None)

    agent_ref = _resolve_agent_with_dataverse(base_url=base_url, headers=headers, agent=agent)
    bot_payload = _dataverse_get(
        f"{base_url}/api/data/v9.2/bots({agent_ref.agent_id})",
        headers,
    )
    yaml_text = _extract_yaml_text(bot_payload)

    if not yaml_text:
        comp_payload = _dataverse_get(
            f"{base_url}/api/data/v9.2/botcomponents?$filter=_botid_value eq {agent_ref.agent_id}&$top=200",
            headers,
        )
        yaml_text = _extract_yaml_text(comp_payload)

    if not yaml_text:
        raise RemoteFetchError(
            "Could not find YAML bot content in Dataverse bot/botcomponent payloads. "
            "Try provider=pac or verify API permissions."
        )

    warnings: list[str] = []
    activities: list[dict] = []
    metadata: dict = {"source": "dataverse"}

    if include_transcripts:
        try:
            activities, tx_meta, tx_warnings = _fetch_transcripts(
                environment=environment,
                agent_id=agent_ref.agent_id,
                transcript_days=transcript_days,
                dataverse_url=base_url,
                headers=headers,
            )
            metadata.update(tx_meta)
            warnings.extend(tx_warnings)
        except RemoteFetchError as exc:
            warnings.append(
                "Transcript fetch skipped: "
                f"{exc}. Provide local transcript JSON manually to enrich conversation analytics."
            )

    return FetchedAgentData(
        agent_id=agent_ref.agent_id,
        agent_name=agent_ref.name,
        bot_content_yaml=yaml_text,
        provider="dataverse",
        transcript_activities=activities,
        metadata=metadata,
        warnings=warnings,
    )


def _ensure_pac_available() -> None:
    if shutil.which("pac"):
        return
    raise RemoteFetchError(
        "Power Platform CLI ('pac') is not available in PATH. "
        "Install it and authenticate, or switch to --provider dataverse."
    )


def _run_pac(args: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    try:
        cp = subprocess.run(
            args,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    except OSError as exc:
        raise RemoteFetchError(f"Failed to run pac command: {exc}") from exc

    if cp.returncode != 0:
        err = _redact_secrets((cp.stderr or cp.stdout or "").strip())
        raise RemoteFetchError(
            f"Command failed ({' '.join(args)}): {err or 'unknown error'}. "
            "Verify 'pac auth create' and environment permissions."
        )
    return cp


def _resolve_agent_with_pac(*, environment: str, agent: str) -> _AgentRef:
    if _is_guid(agent):
        agent_id = agent.lower()
        name = agent
        try:
            rows = _list_agents_with_pac(environment=environment)
            for row in rows:
                if row.agent_id.lower() == agent_id:
                    name = row.name
                    break
        except RemoteFetchError:
            pass
        return _AgentRef(agent_id=agent_id, name=name)

    rows = _list_agents_with_pac(environment=environment)
    needle = agent.strip().lower()

    exact = next((r for r in rows if r.name.lower() == needle), None)
    if exact:
        return exact

    partial = [r for r in rows if needle in r.name.lower()]
    if len(partial) == 1:
        return partial[0]
    if len(partial) > 1:
        options = ", ".join(f"{r.name} ({r.agent_id})" for r in partial[:5])
        raise RemoteFetchError(f"Multiple agents match '{agent}'. Be specific. Matches: {options}")

    raise RemoteFetchError(f"Agent '{agent}' not found via pac copilot list.")


def _list_agents_with_pac(*, environment: str) -> list[_AgentRef]:
    attempts = [
        ["pac", "copilot", "list", "--environment", environment, "--json"],
        ["pac", "copilot", "list", "--environment", environment],
        ["pac", "copilot", "list", "--json"],
        ["pac", "copilot", "list"],
    ]
    last_error: str | None = None
    for cmd in attempts:
        try:
            cp = _run_pac(cmd)
            return _parse_pac_agent_list(cp.stdout)
        except RemoteFetchError as exc:
            last_error = str(exc)

    raise RemoteFetchError(last_error or "Unable to list agents with pac")


def _extract_template_with_pac(*, environment: str, agent_id: str) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp)
        attempts = [
            [
                "pac",
                "copilot",
                "extract-template",
                "--bot",
                agent_id,
                "--environment",
                environment,
                "--outputDirectory",
                str(out_dir),
            ],
            [
                "pac",
                "copilot",
                "extract-template",
                "--bot",
                agent_id,
                "--environment",
                environment,
                "--output",
                str(out_dir),
            ],
            ["pac", "copilot", "extract-template", "--bot", agent_id, "--environment", environment],
            ["pac", "copilot", "extract-template", "--bot", agent_id],
        ]

        last_error: str | None = None
        for cmd in attempts:
            try:
                _run_pac(cmd, cwd=out_dir)
            except RemoteFetchError as exc:
                last_error = str(exc)
                continue

            yaml_files = sorted(
                [*out_dir.rglob("*.yml"), *out_dir.rglob("*.yaml")],
                key=lambda p: p.stat().st_size,
                reverse=True,
            )
            if yaml_files:
                return yaml_files[0].read_text(encoding="utf-8")

        raise RemoteFetchError(
            f"pac extract-template did not produce a YAML file. Last error: {last_error or 'unknown'}"
        )


def _resolve_dataverse_url(*, environment: str, dataverse_url: str | None) -> str:
    env = read_env_config()
    candidate = (dataverse_url or "").strip() or env.mcs_dataverse_url
    if not candidate and environment.startswith(("http://", "https://")):
        candidate = environment
    if not candidate and _looks_like_dataverse_host(environment):
        candidate = f"https://{environment.strip()}"

    env_guid = _extract_guid(environment)
    if not candidate and env_guid:
        candidate = _resolve_dataverse_url_from_pac(env_guid)
    if not candidate:
        raise RemoteFetchError(
            "Dataverse base URL is required for API mode. "
            "Provide a Dataverse URL (or set MCS_DATAVERSE_URL), or pass an environment URL. "
            "Environment GUIDs can be auto-resolved when pac is authenticated."
        )
    return candidate.rstrip("/")


def _resolve_dataverse_url_from_pac(environment_id: str) -> str:
    """Best-effort map of environment GUID to Dataverse URL via pac org list."""
    if not shutil.which("pac"):
        return ""

    attempts = [["pac", "org", "list", "--json"], ["pac", "org", "list"]]
    for cmd in attempts:
        try:
            cp = _run_pac(cmd)
        except RemoteFetchError:
            continue
        url = _extract_environment_url_from_org_list(cp.stdout, environment_id)
        if url:
            return url
    return ""


def _extract_environment_url_from_org_list(stdout: str, environment_id: str) -> str:
    text = (stdout or "").strip()
    if not text:
        return ""

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return ""

    rows: list[dict] = []
    if isinstance(payload, list):
        rows = [item for item in payload if isinstance(item, dict)]
    elif isinstance(payload, dict):
        for key in ("value", "items", "organizations", "environments"):
            value = payload.get(key)
            if isinstance(value, list):
                rows = [item for item in value if isinstance(item, dict)]
                break

    needle = environment_id.strip().lower()
    for row in rows:
        row_id = ""
        for key in ("environmentId", "EnvironmentId", "id", "Id"):
            value = row.get(key)
            if isinstance(value, str) and value.strip():
                row_id = value.strip().lower()
                break
        if row_id != needle:
            continue

        for key in ("url", "Url", "environmentUrl", "EnvironmentUrl", "instanceUrl", "InstanceUrl"):
            value = row.get(key)
            if isinstance(value, str) and value.strip().startswith(("http://", "https://")):
                return value.strip().rstrip("/")

    return ""


def _build_dataverse_headers(*, base_url: str, auth: DataverseAuthConfig | None) -> dict[str, str]:
    token = _resolve_dataverse_token(base_url=base_url, auth=auth)
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "OData-Version": "4.0",
        "OData-MaxVersion": "4.0",
    }


def _resolve_dataverse_token(*, base_url: str, auth: DataverseAuthConfig | None = None) -> str:
    env = read_env_config()
    token = ((auth.token if auth else "") or env.mcs_dataverse_token).strip()
    if token:
        return token

    tenant_id = ((auth.tenant_id if auth else "") or env.mcs_aad_tenant_id).strip()
    client_id = ((auth.client_id if auth else "") or env.mcs_aad_client_id).strip()
    client_secret = ((auth.client_secret if auth else "") or env.mcs_aad_client_secret).strip()

    if not (tenant_id and client_id and client_secret):
        raise RemoteFetchError(
            "Missing Dataverse credentials. Set MCS_DATAVERSE_TOKEN or "
            "MCS_AAD_TENANT_ID + MCS_AAD_CLIENT_ID + MCS_AAD_CLIENT_SECRET."
        )

    scope = ((auth.scope if auth else "") or env.mcs_aad_scope).strip() or f"{base_url}/.default"
    form = urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "client_credentials",
            "scope": scope,
        }
    ).encode("utf-8")

    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    req = Request(token_url, data=form, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except OSError as exc:
        raise RemoteFetchError(f"Failed to acquire OAuth token: {exc}") from exc

    access_token = str(payload.get("access_token", "")).strip()
    if not access_token:
        raise RemoteFetchError("OAuth token response did not include access_token.")
    return access_token


def _find_transcript_row_by_id(*, base_url: str, headers: dict[str, str], transcript_id: str) -> tuple[dict, str]:
    normalized_id = transcript_id.strip()
    guid = normalized_id.lower() if _is_guid(normalized_id) else ""
    candidate_keys = (
        "conversationtranscriptid",
        "msdyn_conversationtranscriptid",
        "transcriptid",
        "sessionid",
    )
    tables = ("conversationtranscripts", "conversationtranscript")

    if guid:
        for table_name in tables:
            for key in candidate_keys:
                query = f"{base_url}/api/data/v9.2/{table_name}?$top=1&$filter={key} eq {guid}"
                try:
                    payload = _dataverse_get(query, headers)
                except RemoteFetchError:
                    continue
                values = payload.get("value", []) if isinstance(payload, dict) else []
                if isinstance(values, list) and values and isinstance(values[0], dict):
                    return values[0], table_name

    for table_name in tables:
        scan_url = f"{base_url}/api/data/v9.2/{table_name}?$top=500&$orderby=createdon desc"
        try:
            payload = _dataverse_get(scan_url, headers)
        except RemoteFetchError:
            continue
        values = payload.get("value", []) if isinstance(payload, dict) else []
        if not isinstance(values, list):
            continue
        for row in values:
            if isinstance(row, dict) and _row_contains_exact_value(row, normalized_id):
                return row, table_name

    raise RemoteFetchError(f"Transcript '{transcript_id}' was not found in Dataverse transcript tables.")


def _row_contains_exact_value(row: dict, needle: str) -> bool:
    target = needle.strip().lower()
    for value in row.values():
        if value is None:
            continue
        if str(value).strip().lower() == target:
            return True
    return False


def _extract_transcript_row_metadata(row: dict) -> dict:
    created_at = _first_str(
        row,
        (
            "createdon",
            "timestamp",
            "createdat",
            "eventtime",
            "messagetime",
            "time",
        ),
    )
    conversation_id = _first_str(row, ("conversationid", "sessionid", "dialogid"))
    speaker = _first_str(row, ("role", "speaker", "from", "author", "sender"))

    data = {}
    if created_at:
        data["transcript_created_at"] = created_at
    if conversation_id:
        data["transcript_conversation_id"] = conversation_id
    if speaker:
        data["transcript_speaker"] = speaker
    return data


def _dataverse_get(url: str, headers: dict[str, str]) -> dict:
    req = Request(url, method="GET")
    for key, value in headers.items():
        req.add_header(key, value)

    try:
        with urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else {}
    except OSError as exc:
        raise RemoteFetchError(f"Dataverse request failed: {url} -> {exc}") from exc


def _resolve_agent_with_dataverse(*, base_url: str, headers: dict[str, str], agent: str) -> _AgentRef:
    listing = _dataverse_get(f"{base_url}/api/data/v9.2/bots?$top=200", headers)
    rows = listing.get("value", []) if isinstance(listing, dict) else []

    if _is_guid(agent):
        needle = agent.lower()
        for row in rows:
            candidate_id = str(row.get("botid", "")).lower()
            if candidate_id == needle:
                name = str(row.get("name") or row.get("displayname") or agent)
                return _AgentRef(agent_id=candidate_id, name=name)
        return _AgentRef(agent_id=needle, name=agent)

    needle_name = agent.strip().lower()
    normalized: list[_AgentRef] = []
    for row in rows:
        candidate_id = str(row.get("botid", "")).strip().lower()
        if not _is_guid(candidate_id):
            continue
        name = str(row.get("name") or row.get("displayname") or candidate_id)
        normalized.append(_AgentRef(agent_id=candidate_id, name=name))

    exact = next((r for r in normalized if r.name.lower() == needle_name), None)
    if exact:
        return exact

    partial = [r for r in normalized if needle_name in r.name.lower()]
    if len(partial) == 1:
        return partial[0]
    if len(partial) > 1:
        options = ", ".join(f"{r.name} ({r.agent_id})" for r in partial[:5])
        raise RemoteFetchError(f"Multiple agents match '{agent}'. Matches: {options}")

    raise RemoteFetchError(f"Agent '{agent}' not found in Dataverse bots table.")


def _extract_yaml_text(payload: object) -> str:
    candidates: list[str] = []

    def _walk(node: object) -> None:
        if isinstance(node, dict):
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)
        elif isinstance(node, str):
            text = node.strip()
            if "entity:" in text and "components:" in text:
                candidates.append(text)

    _walk(payload)

    if not candidates:
        return ""

    candidates.sort(key=len, reverse=True)
    return candidates[0]


def _fetch_transcripts(
    *,
    environment: str,
    agent_id: str,
    transcript_days: int,
    dataverse_url: str | None,
    headers: dict[str, str] | None = None,
) -> tuple[list[dict], dict, list[str]]:
    warnings: list[str] = []

    activities, meta = _fetch_transcripts_dataverse(
        environment=environment,
        agent_id=agent_id,
        transcript_days=transcript_days,
        dataverse_url=dataverse_url,
        headers=headers,
    )
    if activities:
        meta["transcript_source"] = "dataverse"
        return activities, meta, warnings

    warnings.append("No transcript rows found in Dataverse conversation transcript tables.")

    activities, meta = _fetch_transcripts_admin_api(agent_id=agent_id, transcript_days=transcript_days)
    if activities:
        meta["transcript_source"] = "admin-analytics"
        return activities, meta, warnings

    raise RemoteFetchError(
        "No transcripts returned from Dataverse or admin analytics API. "
        "Copilot transcript retention may be limited to recent sessions."
    )


def _fetch_transcripts_dataverse(
    *,
    environment: str,
    agent_id: str,
    transcript_days: int,
    dataverse_url: str | None,
    headers: dict[str, str] | None,
) -> tuple[list[dict], dict]:
    base_url = _resolve_dataverse_url(environment=environment, dataverse_url=dataverse_url)
    request_headers = headers or {
        "Authorization": f"Bearer {_resolve_dataverse_token(base_url=base_url)}",
        "Accept": "application/json",
        "OData-Version": "4.0",
        "OData-MaxVersion": "4.0",
    }

    endpoints = [
        (
            "conversationtranscripts",
            f"{base_url}/api/data/v9.2/conversationtranscripts?$top=200&$orderby=createdon desc",
        ),
        (
            "conversationtranscript",
            f"{base_url}/api/data/v9.2/conversationtranscript?$top=200&$orderby=createdon desc",
        ),
    ]

    rows: list[dict] = []
    source_table = ""

    for table_name, url in endpoints:
        try:
            payload = _dataverse_get(url, request_headers)
        except RemoteFetchError:
            continue
        values = payload.get("value", []) if isinstance(payload, dict) else []
        if not isinstance(values, list) or not values:
            continue
        rows = [r for r in values if isinstance(r, dict)]
        source_table = table_name
        break

    if not rows:
        return [], {"transcript_days": transcript_days}

    filtered = _filter_rows_by_agent(rows, agent_id)
    if not filtered:
        filtered = rows

    activities = _rows_to_activities(filtered)
    meta = {
        "transcript_rows": len(filtered),
        "transcript_days": transcript_days,
        "transcript_table": source_table,
    }
    return activities, meta


def _fetch_transcripts_admin_api(*, agent_id: str, transcript_days: int) -> tuple[list[dict], dict]:
    env = read_env_config()
    endpoint = env.mcs_admin_sessions_url
    token = env.mcs_admin_api_token

    if not endpoint or not token:
        return [], {"transcript_days": transcript_days}

    query = urlencode({"agentId": agent_id, "days": transcript_days})
    url = endpoint + ("&" if "?" in endpoint else "?") + query

    req = Request(url, method="GET")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/json")

    try:
        with urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except OSError as exc:
        raise RemoteFetchError(f"Admin analytics transcript request failed: {exc}") from exc

    rows: list[dict] = []
    if isinstance(payload, dict):
        for key in ("value", "sessions", "items", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                rows = [v for v in value if isinstance(v, dict)]
                break
    elif isinstance(payload, list):
        rows = [v for v in payload if isinstance(v, dict)]

    if not rows:
        return [], {"transcript_days": transcript_days}

    activities = _rows_to_activities(rows)
    return activities, {"transcript_rows": len(rows), "transcript_days": transcript_days}


def _filter_rows_by_agent(rows: list[dict], agent_id: str) -> list[dict]:
    needle = agent_id.lower()
    filtered: list[dict] = []
    for row in rows:
        for key, value in row.items():
            if "agent" not in key.lower() and "bot" not in key.lower():
                continue
            if isinstance(value, str) and value.lower() == needle:
                filtered.append(row)
                break
    return filtered


def _rows_to_activities(rows: list[dict]) -> list[dict]:
    activities: list[dict] = []
    for idx, row in enumerate(rows):
        text = _first_str(
            row,
            (
                "message",
                "text",
                "transcript",
                "utterance",
                "content",
                "prompt",
                "response",
            ),
        )
        if not text:
            continue

        role_raw = _first_str(row, ("role", "speaker", "from", "author", "sender"))
        role = "bot" if _is_bot_role(role_raw) else "user"

        timestamp = _first_str(
            row,
            (
                "timestamp",
                "createdon",
                "createdat",
                "eventtime",
                "messagetime",
                "time",
            ),
        )

        conversation_id = _first_str(row, ("conversationid", "sessionid", "dialogid"))

        activity = {
            "type": "message",
            "timestamp": timestamp,
            "from": {"role": role, "name": role_raw or role},
            "conversation": {"id": conversation_id or "remote-session"},
            "text": text,
            "channelData": {"webchat:internal:position": idx * 1000},
        }
        activities.append(activity)

    return activities


def _first_str(row: dict, candidates: tuple[str, ...]) -> str:
    for key in candidates:
        for row_key, value in row.items():
            if key.lower() != row_key.lower():
                continue
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
    return ""


def _is_bot_role(role: str | None) -> bool:
    if not role:
        return False
    norm = role.strip().lower()
    return norm in {"bot", "assistant", "agent", "copilot"}


def _is_guid(value: str) -> bool:
    return bool(_GUID_RE.match((value or "").strip()))


def _extract_guid(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    if _is_guid(text):
        return text.lower()
    match = _GUID_SEARCH_RE.search(text)
    return match.group(0).lower() if match else ""


def _looks_like_dataverse_host(value: str) -> bool:
    text = (value or "").strip().lower()
    if not text or "://" in text:
        return False
    return text.endswith(".crm.dynamics.com") or text.endswith(".dynamics.com")


def _parse_pac_agent_list(stdout: str) -> list[_AgentRef]:
    text = (stdout or "").strip()
    if not text:
        return []

    parsed = _parse_pac_agent_list_json(text)
    if parsed:
        return parsed

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    rows: list[_AgentRef] = []
    for line in lines:
        match = re.search(_GUID_RE.pattern.strip("^$"), line)
        if not match:
            continue
        agent_id = match.group(0).lower()
        prefix = line[: match.start()].strip(" |\t")
        suffix = line[match.end() :].strip(" |\t")
        name = prefix or suffix or agent_id
        rows.append(_AgentRef(agent_id=agent_id, name=name))
    return rows


def _parse_pac_agent_list_json(text: str) -> list[_AgentRef]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []

    if isinstance(payload, dict):
        if isinstance(payload.get("value"), list):
            rows = payload["value"]
        elif isinstance(payload.get("items"), list):
            rows = payload["items"]
        else:
            rows = []
    elif isinstance(payload, list):
        rows = payload
    else:
        rows = []

    refs: list[_AgentRef] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        agent_id = ""
        for key in ("botid", "botId", "id", "Id", "BotId"):
            value = item.get(key)
            if isinstance(value, str) and _is_guid(value):
                agent_id = value.lower()
                break
        if not agent_id:
            continue
        name = ""
        for key in ("name", "displayName", "displayname", "Name"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                name = value.strip()
                break
        refs.append(_AgentRef(agent_id=agent_id, name=name or agent_id))

    return refs


def _redact_secrets(text: str) -> str:
    if not text:
        return ""

    result = text
    env = read_env_config()
    for secret in (env.mcs_dataverse_token, env.mcs_aad_client_secret, env.mcs_admin_api_token):
        if secret:
            result = result.replace(secret, "***")
    return result
