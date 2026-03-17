"""Tests for remote fetch helpers."""

from __future__ import annotations

from remote_fetch import (
    check_dataverse_connection,
    DataverseAuthConfig,
    _parse_pac_agent_list,
    _rows_to_activities,
    fetch_transcript_by_id,
)


def test_parse_pac_agent_list_from_json_payload():
    payload = """
    [
      {
        "botid": "4d955d6c-26f2-4e6f-8ebf-bf39f0e47eac",
        "displayName": "Legal Copilot"
      },
      {
        "id": "3434ca67-82b1-40ab-b66d-0f9f93adfca7",
        "name": "HR Helper"
      }
    ]
    """

    rows = _parse_pac_agent_list(payload)

    assert len(rows) == 2
    assert rows[0].agent_id == "4d955d6c-26f2-4e6f-8ebf-bf39f0e47eac"
    assert rows[0].name == "Legal Copilot"
    assert rows[1].name == "HR Helper"


def test_parse_pac_agent_list_from_text_table():
    payload = """
    Name                BotId
    ------------------  ------------------------------------
    Legal Copilot       4d955d6c-26f2-4e6f-8ebf-bf39f0e47eac
    HR Helper           3434ca67-82b1-40ab-b66d-0f9f93adfca7
    """

    rows = _parse_pac_agent_list(payload)

    assert len(rows) == 2
    assert rows[0].name == "Legal Copilot"
    assert rows[1].agent_id == "3434ca67-82b1-40ab-b66d-0f9f93adfca7"


def test_rows_to_activities_normalizes_message_role_and_position():
    rows = [
        {
            "createdon": "2026-03-12T09:11:00Z",
            "speaker": "assistant",
            "message": "Hello from bot",
            "conversationid": "conv-1",
        },
        {
            "createdon": "2026-03-12T09:11:02Z",
            "speaker": "user",
            "text": "Thanks",
            "conversationid": "conv-1",
        },
    ]

    activities = _rows_to_activities(rows)

    assert len(activities) == 2
    assert activities[0]["from"]["role"] == "bot"
    assert activities[0]["channelData"]["webchat:internal:position"] == 0
    assert activities[1]["from"]["role"] == "user"
    assert activities[1]["channelData"]["webchat:internal:position"] == 1000


def test_fetch_transcript_by_id_uses_dataverse_guid_lookup(monkeypatch):
    def fake_token(*, base_url, auth=None):
        return "token"

    def fake_get(url, headers):
        assert headers.get("Authorization") == "Bearer token"
        assert "conversationtranscripts" in url
        return {
            "value": [
                {
                    "conversationtranscriptid": "4d955d6c-26f2-4e6f-8ebf-bf39f0e47eac",
                    "message": "I need help with PTO",
                    "speaker": "user",
                    "createdon": "2026-03-12T09:11:00Z",
                    "conversationid": "conv-42",
                }
            ]
        }

    monkeypatch.setattr("remote_fetch._resolve_dataverse_token", fake_token)
    monkeypatch.setattr("remote_fetch._dataverse_get", fake_get)

    activities, metadata = fetch_transcript_by_id(
        environment="https://contoso.crm.dynamics.com",
        transcript_id="4d955d6c-26f2-4e6f-8ebf-bf39f0e47eac",
    )

    assert len(activities) == 1
    assert activities[0]["text"] == "I need help with PTO"
    assert metadata["transcript_source"] == "dataverse"


def test_fetch_transcript_by_id_supports_manual_auth_overrides(monkeypatch):
    calls = {"token": 0}

    def fake_token(*, base_url, auth=None):
        calls["token"] += 1
        assert auth is not None
        assert auth.tenant_id == "tenant"
        assert auth.client_id == "client"
        assert auth.client_secret == "secret"
        return "manual-token"

    def fake_get(url, headers):
        assert headers.get("Authorization") == "Bearer manual-token"
        return {
            "value": [
                {
                    "conversationtranscriptid": "abc",
                    "text": "Bot response",
                    "role": "assistant",
                    "createdon": "2026-03-12T10:00:00Z",
                }
            ]
        }

    monkeypatch.setattr("remote_fetch._resolve_dataverse_token", fake_token)
    monkeypatch.setattr("remote_fetch._dataverse_get", fake_get)

    activities, _ = fetch_transcript_by_id(
        environment="https://contoso.crm.dynamics.com",
        transcript_id="abc",
        auth=DataverseAuthConfig(tenant_id="tenant", client_id="client", client_secret="secret"),
    )

    assert calls["token"] == 1
    assert activities[0]["from"]["role"] == "bot"


def test_dataverse_connection_returns_whoami_metadata(monkeypatch):
    def fake_token(*, base_url, auth=None):
        return "conn-token"

    def fake_get(url, headers):
        assert url.endswith("/api/data/v9.2/WhoAmI()")
        assert headers.get("Authorization") == "Bearer conn-token"
        return {
            "UserId": "11111111-1111-1111-1111-111111111111",
            "BusinessUnitId": "22222222-2222-2222-2222-222222222222",
            "OrganizationId": "33333333-3333-3333-3333-333333333333",
        }

    monkeypatch.setattr("remote_fetch._resolve_dataverse_token", fake_token)
    monkeypatch.setattr("remote_fetch._dataverse_get", fake_get)

    result = check_dataverse_connection(environment="https://contoso.crm.dynamics.com")

    assert result["dataverse_url"] == "https://contoso.crm.dynamics.com"
    assert result["user_id"] == "11111111-1111-1111-1111-111111111111"
