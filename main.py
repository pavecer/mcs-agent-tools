"""CLI entry point for the Power Platform Agent Renamer.

Usage examples::

    # Rename using a ZIP export
    uv run python main.py solution.zip --agent-name "ACME Legal Bot" --solution-name "ACMELegalBot"

    # Rename using an extracted folder
    uv run python main.py ./AskLegalMicrosoft_1_0_0_4 --agent-name "My Copy" --solution-name "MyLegalCopy"

    # Specify custom schema name
    uv run python main.py solution.zip -a "ACME Copy" -s "ACMECopy" --schema copilots_new_acme_copy

    # Inspect only (no rename)
    uv run python main.py solution.zip --inspect
"""

from __future__ import annotations

from pathlib import Path

import typer
from loguru import logger
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from models import RenameConfig
from renamer import inspect_solution, inspect_zip, rename_solution, sanitize_schema_name

app = typer.Typer(help="Rename a Power Platform Copilot Studio agent solution export.")
console = Console()


@app.command()
def main(
    source: Path = typer.Argument(
        ...,
        help="Path to the solution ZIP file or extracted solution folder.",
        exists=True,
    ),
    agent_name: str = typer.Option(
        ...,
        "--agent-name",
        "-a",
        help="New display name for the agent (e.g. 'ACME Legal Bot').",
        prompt="New agent display name",
    ),
    solution_name: str = typer.Option(
        ...,
        "--solution-name",
        "-s",
        help="New unique name for the solution (letters/digits/underscores only, e.g. 'ACMELegalBot').",
        prompt="New solution unique name",
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
) -> None:
    """Rename all references inside a Power Platform solution export."""

    # ── Detect source info ───────────────────────────────────────────────────
    console.print(f"\n[bold cyan]Power Platform Agent Renamer[/bold cyan]\n")

    source = source.resolve()
    if source.suffix.lower() == ".zip":
        info = inspect_zip(source)
    else:
        info = inspect_solution(source)

    _print_info(info)

    if inspect:
        raise typer.Exit()

    # ── Preview derived names ────────────────────────────────────────────────
    from renamer import derive_schema_name

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


if __name__ == "__main__":
    app()
