"""Tests for fetch-mode CLI behavior."""

from __future__ import annotations

from typer.testing import CliRunner

import main as main_module
from remote_fetch import FetchedAgentData


runner = CliRunner()


def test_fetch_requires_env_and_agent():
    result = runner.invoke(main_module.app, ["--fetch"])

    assert result.exit_code == 2


def test_local_mode_requires_source_when_fetch_not_used():
    result = runner.invoke(main_module.app, [])

    assert result.exit_code == 2


def test_fetch_mode_generates_report_file(monkeypatch, tmp_path):
    def fake_fetch_agent_data(**_: object) -> FetchedAgentData:
        return FetchedAgentData(
            agent_id="4d955d6c-26f2-4e6f-8ebf-bf39f0e47eac",
            agent_name="Legal Copilot",
            provider="pac",
            bot_content_yaml="""
entity:
  schemaName: copilots_header_legal
  displayName: Legal Copilot
  cdsBotId: 4d955d6c-26f2-4e6f-8ebf-bf39f0e47eac
  configuration:
    channels: []
components: []
""",
            transcript_activities=[],
            metadata={},
            warnings=[],
        )

    monkeypatch.setattr(main_module, "fetch_agent_data", fake_fetch_agent_data)

    output = tmp_path / "report.md"
    result = runner.invoke(
        main_module.app,
        [
            "--fetch",
            "--env",
            "dev",
            "--agent",
            "Legal Copilot",
            "--report-output",
            str(output),
        ],
    )

    assert result.exit_code == 0
    assert output.exists()
    report = output.read_text(encoding="utf-8")
    assert "Remote Fetch Summary" in report
    assert "Legal Copilot" in report
