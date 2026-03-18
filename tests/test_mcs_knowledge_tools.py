"""Tests for knowledge source/tool extraction and report rendering."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from mcs_models import MCSBotProfile, MCSConversationTimeline, MCSExternalTool, MCSKnowledgeSource
from mcs_parser import parse_yaml, parse_zip_bytes
from mcs_renderer import render_knowledge_sources_and_tools
from mcs_renderer import render_report_sections


def test_parse_yaml_extracts_knowledge_sources_and_tools(tmp_path: Path):
    content = """
entity:
  schemaName: copilots_test
  displayName: Test Agent
  configuration: {}
spec:
  knowledgeSources:
    publicSites:
      - name: Contoso FAQ
        url: https://www.contoso.com/faq
    sharepointSites:
      - name: AI-Projects
        siteUrl: https://contoso.sharepoint.com/sites/AI-Projects
        siteId: sp-123
    dataverse:
      - name: Cases
        tableName: incident
    files:
      - name: Handbook
        filePath: /docs/handbook.pdf
components:
  - kind: DialogComponent
    displayName: Main Topic
    schemaName: copilots_test.topic.Main
    dialog:
      beginDialog:
        kind: OnRecognizedIntent
        actions:
          - kind: HttpRequestAction
            displayName: Call API
            method: GET
            url: https://api.contoso.com/customers
            connectorId: shared_http
            connectionProperties:
              mode: user
          - kind: InvokeAIBuilderModelAction
            modelName: TicketClassifier
            connectionProperties:
              mode: maker
          - kind: InvokeExternalAgentTaskAction
            taskName: MCP Inventory Search
            serverUrl: https://mcp.contoso.com
connectionReferences:
  shared_azuredevops:
    displayName: Azure DevOps Connector
    connectorId: shared_azuredevops
    connectionProperties:
      mode: invokingUser
"""

    yml = tmp_path / "botContent.yml"
    yml.write_text(content, encoding="utf-8")

    profile, _ = parse_yaml(yml)

    assert any(s.source_type == "Website" and s.name == "Contoso FAQ" for s in profile.knowledge_sources)
    assert any(s.source_type == "SharePoint" and s.site_id == "sp-123" for s in profile.knowledge_sources)
    assert any(s.source_type == "Dataverse" and s.location == "incident" for s in profile.knowledge_sources)
    assert any(s.source_type == "File" and s.location == "/docs/handbook.pdf" for s in profile.knowledge_sources)

    types = {t.tool_type for t in profile.external_tools}
    assert "HTTP Request" in types
    assert "AI Builder Model" in types
    assert "External Agent / MCP" in types
    assert "Connector" in types

    http_tool = next(t for t in profile.external_tools if t.tool_type == "HTTP Request")
    assert http_tool.connector_id == "shared_http"
    assert http_tool.auth_mode == "User identity"



def test_parse_zip_bytes_extracts_profile_from_snapshot_zip():
    yml = """
entity:
  schemaName: copilots_test
  displayName: Snapshot Agent
  configuration:
    channels: []
components: []
"""

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("snapshot/botContent.yml", yml)

    profile = parse_zip_bytes(buf.getvalue())

    assert profile.display_name == "Snapshot Agent"
    assert profile.schema_name == "copilots_test"


def test_render_knowledge_sources_and_tools_marks_access_and_auth(monkeypatch):
    profile = MCSBotProfile(
        knowledge_sources=[
            MCSKnowledgeSource(
                name="Contoso FAQ",
                source_type="Website",
                location="https://www.contoso.com/faq",
            ),
            MCSKnowledgeSource(
                name="Broken Site",
                source_type="Website",
                location="https://www.contoso.com/missing",
            ),
            MCSKnowledgeSource(name="Cases", source_type="Dataverse", location=None),
        ],
        external_tools=[
            MCSExternalTool(
                name="Azure DevOps Connector",
                tool_type="Connector",
                connector_id="shared_azuredevops",
                auth_mode="User identity",
            ),
            MCSExternalTool(
                name="Customer Creation Flow",
                tool_type="Cloud Flow",
                auth_mode="Maker/service account",
            ),
        ],
    )

    def fake_check(url: str, timeout_s: float = 5.0):
        if url.endswith("/faq"):
            return True, "HTTP 200"
        return False, "HTTP 404"

    monkeypatch.setattr("mcs_renderer._check_public_url", fake_check)

    report = render_knowledge_sources_and_tools(profile)

    assert "## Knowledge Sources & External Tools" in report
    assert "Contoso FAQ" in report
    assert "Accessible✅" in report
    assert "Broken Site" in report
    assert "Inaccessible⚠️" in report
    assert "Missing Resource⚠️" in report

    assert "Azure DevOps Connector" in report
    assert "uses **user identity**" in report
    assert "Customer Creation Flow" in report
    assert "service account (maker auth)" in report


def test_render_report_sections_exposes_dedicated_knowledge_tools_section():
    profile = MCSBotProfile(
        display_name="Test Agent",
        knowledge_sources=[
            MCSKnowledgeSource(name="Contoso FAQ", source_type="Website", location="https://www.contoso.com/faq")
        ],
    )

    sections = render_report_sections(profile, timeline=MCSConversationTimeline())

    # The section should be present and profile should no longer inline this block.
    assert "knowledge_tools" in sections
    assert "## Knowledge Sources & External Tools" in sections["knowledge_tools"]
    assert "## Knowledge Sources & External Tools" not in sections["profile"]
