# PP Agent Renamer

Renames all references inside a **Microsoft Power Platform / Copilot Studio** solution export so it can be imported as a new, standalone copy of an existing agent.

## What it does

When you export a Copilot Studio agent from Power Platform and want to import it again under a different name (e.g. to create a copy or sandbox version), the ZIP contains hundreds of files that all reference the original bot's schema name and solution name. Importing the ZIP as-is simply overwrites the existing agent.

This tool updates every reference so the solution is treated as a brand-new agent on import:

| What changes | Where |
|---|---|
| Bot schema name (`copilots_new_bck_asklegal` → new) | All `botcomponent.xml` files, `bot.xml`, `configuration.json`, `data` YAML files |
| Bot display name | `bot.xml`, `solution.xml`, `gpt.default/botcomponent.xml` |
| Solution unique name | `solution.xml` |
| Folder names | `bots/{schema}/`, `botcomponents/{schema}.*/` |

## Quick Start

### Web UI

```bash
cp .env.example .env   # edit ports if needed
uv sync
uv run reflex run
```

Open http://localhost:3000:

1. Drag & drop your `.zip` solution export
2. Enter the **new agent display name** (e.g. `ACME Legal Bot`)
3. Enter the **new solution unique name** (e.g. `ACMELegalBot`)
4. Click **Rename Solution**
5. Download the renamed ZIP and import it into Power Platform

### CLI

```bash
uv sync

# Basic usage
uv run python main.py AskLegalMicrosoft_1_0_0_4.zip \
    --agent-name "ACME Legal Bot" \
    --solution-name "ACMELegalBot"

# Use extracted folder instead of ZIP
uv run python main.py ./AskLegalMicrosoft_1_0_0_4 \
    --agent-name "ACME Copy" \
    --solution-name "ACMECopy"

# Override the auto-derived schema name
uv run python main.py solution.zip \
    -a "ACME Legal Bot" -s "ACMELegalBot" \
    --schema copilots_new_acme_legal_bot

# Inspect only — no changes
uv run python main.py solution.zip --inspect

# Specify custom output path
uv run python main.py solution.zip -a "Copy" -s "MyCopy" -o ./output/my_copy.zip
```

## Project Structure

```
main.py          CLI entry point (Typer + Rich)
models.py        Pydantic models (RenameConfig, RenameResult, SolutionInfo)
renamer.py       Core renaming logic (detection, content replace, folder rename, ZIP)
rxconfig.py      Reflex app config
web/
  state.py       Reflex state (upload, processing, download)
  components.py  UI components (upload area, info panels, result card)
  web.py         Page definitions and Reflex app setup
```

## Configuration

| Variable | Default | Description |
|---|---|---|
| `REFLEX_ENV` | `dev` | `dev` = two ports, `prod` = single-port mode |
| `FRONTEND_PORT` | `3000` | Frontend port (dev only) |
| `BACKEND_PORT` | `8000` | Backend port (dev only) |
| `PORT` | `2009` | Port for prod single-port mode |

## Deployment (Docker / Coolify)

```bash
docker build -t pp-agent-renamer .
docker run -p 2009:2009 -e REFLEX_ENV=prod -e PORT=2009 pp-agent-renamer
```

## Development

```bash
uv sync
uv run ruff check .
uv run ruff format .
uv run reflex run
```

## How schema names are derived

Power Platform bot schema names follow the pattern `{namespace}_{publisher_prefix}_{logical_name}`,  
e.g. `copilots_new_bck_asklegal`.

The tool extracts the prefix (first two underscore-separated segments, e.g. `copilots_new_`) and appends a sanitized version of your new agent display name:

```
"ACME Legal Bot"  →  copilots_new_acme_legal_bot
"My Copy"         →  copilots_new_my_copy
```

You can override this with `--schema` (CLI) or by editing the derived schema preview field.

## Caveats

- The tool performs **text replacement** on all XML, JSON, and YAML (`data`) files; binary files (e.g. `.xlsx` knowledge files) are skipped automatically.
- Always test-import into a **development environment** before using in production.
- This tool does not update any **GUIDs** inside the solution — Power Platform generates new GUIDs on import, so this is not required.
