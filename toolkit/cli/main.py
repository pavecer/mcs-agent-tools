"""CLI entry point for the Power Platform Agent Renamer.

Usage examples::

    # Rename using a ZIP export
    uv run python main.py solution.zip --agent-name "My New Bot" --solution-name "MyNewBot"

    # Rename using an extracted folder
    uv run python main.py ./MySolution_1_0_0_0 --agent-name "My Bot Copy" --solution-name "MyBotCopy"

    # Specify custom schema name
    uv run python main.py solution.zip -a "My Bot Copy" -s "MyBotCopy" --schema copilots_new_my_bot_copy

    # Inspect only (no rename)
    uv run python main.py solution.zip --inspect
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Load environment variables from .env file before any imports that use them
load_dotenv()

from toolkit.core.models import RenameConfig
from toolkit.core.remote_fetch import RemoteFetchError, fetch_agent_data
from toolkit.core.renamer import derive_schema_name, inspect_solution, inspect_zip, rename_solution
from toolkit.mcs.models import MCSConversationTimeline
from toolkit.mcs.parser import parse_yaml
from toolkit.mcs.renderer import render_report
from toolkit.mcs.timeline import build_timeline

app = typer.Typer(help="Rename a Power Platform Copilot Studio agent solution export.")
console = Console()


@app.command()
def main(
    source: Path | None = typer.Argument(
        None,
        help="Path to the solution ZIP file or extracted solution folder.",
        exists=True,
    ),
    agent_name: str | None = typer.Option(
        None,
        "--agent-name",
        "-a",
        help="New display name for the agent (e.g. 'My New Bot').",
    ),
    solution_name: str | None = typer.Option(
        None,
        "--solution-name",
        "-s",
        help="New unique name for the solution (letters/digits/underscores only, e.g. 'MyNewBot').",
    ),
    schema: str | None = typer.Option(
        None,
        "--schema",
        help="Override the derived bot schema name (optional, auto-derived if omitted).",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Output ZIP path. Defaults to <solution_name>.zip in the current directory.",
    ),
    inspect: bool = typer.Option(
        False,
        "--inspect",
        help="Only display solution info, do not perform any renaming.",
    ),
    fetch: bool = typer.Option(
        False,
        "--fetch",
        help="Fetch latest bot content from an environment and generate analysis report.",
    ),
    env: str | None = typer.Option(
        None,
        "--env",
        help="Environment identifier or URL.",
    ),
    agent: str | None = typer.Option(
        None,
        "--agent",
        help="Agent identifier (GUID) or display name.",
    ),
    provider: str = typer.Option(
        "auto",
        "--provider",
        help="Remote provider: auto, pac, dataverse.",
    ),
    dataverse_url: str | None = typer.Option(
        None,
        "--dataverse-url",
        help="Dataverse base URL for API mode (optional if --env is already a URL).",
    ),
    transcripts: bool = typer.Option(
        True,
        "--transcripts/--no-transcripts",
        help="Fetch recent transcripts for conversation analytics when available.",
    ),
    transcript_days: int = typer.Option(
        7,
        "--transcript-days",
        min=1,
        max=29,
        help="Recent transcript window in days (Dataverse retention is typically 29 days).",
    ),
    report_output: Path | None = typer.Option(
        None,
        "--report-output",
        help="Output Markdown report path for fetch mode.",
    ),
) -> None:
    """Rename all references inside a Power Platform solution export."""

    if fetch:
        _run_remote_analysis(
            env=env,
            agent=agent,
            provider=provider,
            dataverse_url=dataverse_url,
            include_transcripts=transcripts,
            transcript_days=transcript_days,
            report_output=report_output,
        )
        return

    if source is None:
        raise typer.BadParameter(
            "Missing source path. Provide SOURCE for local rename flow, or use --fetch with --env and --agent."
        )

    # ── Detect source info ───────────────────────────────────────────────────
    console.print("\n[bold cyan]Power Platform Agent Toolkit[/bold cyan]\n")

    source = source.resolve()
    if source.suffix.lower() == ".zip":
        info = inspect_zip(source)
    else:
        info = inspect_solution(source)

    _print_info(info)

    if inspect:
        raise typer.Exit()

    if not agent_name:
        agent_name = typer.prompt("New agent display name").strip()
    if not solution_name:
        solution_name = typer.prompt("New solution unique name").strip()

    # ── Preview derived names ────────────────────────────────────────────────
    derived_schema = schema or derive_schema_name(info.bot_schema_name, agent_name)

    table = Table(title="Rename Preview", show_header=True, header_style="bold magenta")
    table.add_column("Field")
    table.add_column("Old Value", style="yellow")
    table.add_column("New Value", style="green")
    table.add_row("Agent display name", info.bot_display_name, agent_name)
    table.add_row("Solution unique name", info.solution_unique_name, solution_name)
    table.add_row("Bot schema name", info.bot_schema_name, derived_schema)
    console.print(table)

    confirmed = typer.confirm("\nProceed with renaming?", default=True)
    if not confirmed:
        console.print("[yellow]Aborted.[/yellow]")
        raise typer.Exit()

    # ── Determine output path ────────────────────────────────────────────────
    output_path = output or Path(f"{solution_name}.zip")

    # ── Run rename ────────────────────────────────────────────────────────────
    config = RenameConfig(
        source_path=source,
        new_agent_name=agent_name,
        new_solution_name=solution_name,
        new_bot_schema_name=schema,
        output_path=output_path.resolve(),
    )

    with console.status("[green]Renaming solution…[/green]"):
        result = rename_solution(config)

    # ── Print result ──────────────────────────────────────────────────────────
    console.print(
        Panel(
            f"[green]✓ Done![/green]\n\n"
            f"  Files modified  : {result.files_modified}\n"
            f"  Folders renamed : {result.folders_renamed}\n"
            f"  Output ZIP      : [bold]{result.output_path}[/bold]",
            title="Result",
            border_style="green",
        )
    )

    if result.warnings:
        for w in result.warnings:
            console.print(f"[yellow]⚠ {w}[/yellow]")


def _print_info(info) -> None:
    table = Table(title="Detected Solution Info", show_header=True, header_style="bold blue")
    table.add_column("Field")
    table.add_column("Value", style="cyan")
    table.add_row("Bot schema name", info.bot_schema_name)
    table.add_row("Bot display name", info.bot_display_name)
    table.add_row("Solution unique name", info.solution_unique_name)
    table.add_row("Solution display name", info.solution_display_name)
    table.add_row("Botcomponent folders", str(len(info.botcomponent_folders)))
    console.print(table)


def _run_remote_analysis(
    *,
    env: str | None,
    agent: str | None,
    provider: str,
    dataverse_url: str | None,
    include_transcripts: bool,
    transcript_days: int,
    report_output: Path | None,
) -> None:
    if not env:
        raise typer.BadParameter("--env is required when --fetch is set.")
    if not agent:
        raise typer.BadParameter("--agent is required when --fetch is set.")

    console.print("\n[bold cyan]Power Platform Agent Toolkit[/bold cyan]\n")
    console.print("[bold]Mode:[/bold] Remote analysis fetch")

    try:
        with console.status("[green]Fetching remote agent content...[/green]"):
            fetched = fetch_agent_data(
                environment=env,
                agent=agent,
                provider=provider,
                include_transcripts=include_transcripts,
                transcript_days=transcript_days,
                dataverse_url=dataverse_url,
            )
    except RemoteFetchError as exc:
        console.print(
            Panel(
                "[red]Remote fetch failed.[/red]\n\n"
                f"Reason: {exc}\n\n"
                "Fallback: provide a local export ZIP to run analysis manually.",
                title="Fetch Error",
                border_style="red",
            )
        )
        raise typer.Exit(code=2) from exc

    with tempfile.TemporaryDirectory() as tmp_dir:
        bot_content_path = Path(tmp_dir) / "botContent.yml"
        bot_content_path.write_text(fetched.bot_content_yaml, encoding="utf-8")

        profile, schema_lookup = parse_yaml(bot_content_path)
        timeline = (
            build_timeline(fetched.transcript_activities, schema_lookup)
            if fetched.transcript_activities
            else MCSConversationTimeline()
        )

    report = render_report(profile, timeline)

    notes: list[str] = []
    notes.append(f"Provider: {fetched.provider}")
    notes.append(f"Agent: {fetched.agent_name} ({fetched.agent_id})")
    transcript_count = len(fetched.transcript_activities)
    notes.append(f"Transcript activities: {transcript_count}")
    notes.extend(f"Warning: {warning}" for warning in fetched.warnings)

    notes_md = "\n".join(f"- {item}" for item in notes)
    report_with_notes = "\n".join(["## Remote Fetch Summary", "", notes_md, "", report])

    output_path = report_output or Path(f"{_slugify_filename(fetched.agent_name)}_analysis_report.md")
    output_path = output_path.resolve()
    output_path.write_text(report_with_notes, encoding="utf-8")

    console.print(
        Panel(
            "[green]Analysis report generated.[/green]\n\n"
            f"  Provider           : {fetched.provider}\n"
            f"  Agent              : {fetched.agent_name}\n"
            f"  Transcript events  : {transcript_count}\n"
            f"  Output report      : [bold]{output_path}[/bold]",
            title="Result",
            border_style="green",
        )
    )

    if fetched.warnings:
        for warning in fetched.warnings:
            console.print(f"[yellow]Warning: {warning}[/yellow]")


def _slugify_filename(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in (value or "agent"))
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    cleaned = cleaned.strip("_")
    return cleaned or "agent"


if __name__ == "__main__":
    app()
