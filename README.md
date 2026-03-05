# PP Agent Toolkit

A **Microsoft Power Platform / Copilot Studio** developer tool with three capabilities, all available through a single web UI or CLI:

| Tab | What it does |
|---|---|
| **Rename** | Rename all references inside a solution export so it can be imported as a new, standalone agent |
| **Visualise** | Parse the solution ZIP and render a structured Markdown + Mermaid diagram report of the agent's AI configuration, components, and topic connection graph |
| **Validate** | Analyse the agent's system instructions against model-specific best practices (GPT-4.1 and higher) and surface actionable rule-by-rule findings |

---

## Rename

When you export a Copilot Studio agent from Power Platform and want to import it again under a different name (e.g. to create a copy or sandbox version), the ZIP contains hundreds of files that all reference the original bot's schema name and solution name. Importing the ZIP as-is simply overwrites the existing agent.

This tool updates every reference so the solution is treated as a brand-new agent on import:

| What changes | Where |
|---|---|
| Bot schema name (`copilots_new_prefix_botname` → new) | All `botcomponent.xml` files, `bot.xml`, `configuration.json`, `data` YAML files |
| Bot display name | `bot.xml`, `solution.xml`, `gpt.default/botcomponent.xml` |
| Solution unique name | `solution.xml` |
| Folder names | `bots/{schema}/`, `botcomponents/{schema}.*/` |

---

## Visualise

After uploading a solution ZIP the **Visualise** tab automatically parses the solution and generates a report containing:

- **AI Configuration** — model hint, web browsing, code interpreter, use model knowledge, and a preview of the system instructions
- **Agent Profile** — schema name, channels, recognizer kind, orchestrator flag
- **Components** — summary by category (User Topics, System Topics, Automation Topics, Knowledge, Skills, Custom Entities, Variables, Settings) with active/inactive counts
- **Topic Connection Graph** — interactive Mermaid flowchart of all `BeginDialog` calls between topics, including conditional edges

---

## Validate

The **Validate** tab analyses the agent's system instructions against a curated set of best-practice rules for the model the agent is configured to use.

Supported models (GPT-4.1 and higher):

| Model | Key focus areas |
|---|---|
| GPT-4.1 | Persona, purpose, explicit scope constraints, deterministic language |
| GPT-4.1 Mini | Conciseness, single domain, flat rule structure |
| GPT-4.1 Nano | Ultra-concise (≤ 5 directives), no complex logic |
| GPT-5 | Grounding rules, output schemas, tight scope constraints |
| GPT-5 Chat | Mandatory grounding, instruction-override guard, escalation path |
| o1 | Goal-oriented only — no redundant reasoning-process directives |
| o3 | Self-validation criteria, precise output schemas, strong grounding |
| o4-mini | Concise + goal-oriented, no chain-of-thought instructions |

Each run returns a rule-by-rule report with **PASS / WARN / FAIL** verdicts and actionable detail for every check. A collapsible "Show Best Practices" section surfaces the full guidance document for the detected model.

---

## Quick Start

### Web UI

```bash
cp .env.example .env   # edit ports if needed
uv sync
uv run reflex run
```

Open http://localhost:3000:

**Rename tab**
1. Drag & drop your `.zip` solution export
2. Enter the **new agent display name** (e.g. `My New Bot`)
3. Enter the **new solution display name** (e.g. `My New Bot Solution`)
4. Click **Rename Solution**
5. Download the renamed ZIP and import it into Power Platform

**Visualise tab** — upload a ZIP and the report renders automatically.

**Validate tab** — upload a ZIP and validation runs automatically alongside visualisation.

### CLI (rename only)

```bash
uv sync

# Basic usage
uv run python main.py MySolution_1_0_0_0.zip \
    --agent-name "My New Bot" \
    --solution-name "MyNewBot"

# Use extracted folder instead of ZIP
uv run python main.py ./MySolution_1_0_0_0 \
    --agent-name "My Bot Copy" \
    --solution-name "MyBotCopy"

# Override the auto-derived schema name
uv run python main.py solution.zip \
    -a "My New Bot" -s "MyNewBot" \
    --schema copilots_new_my_new_bot

# Inspect only — no changes
uv run python main.py solution.zip --inspect

# Specify custom output path
uv run python main.py solution.zip -a "Copy" -s "MyCopy" -o ./output/my_copy.zip
```

---

## Project Structure

```
main.py              CLI entry point (Typer + Rich) — rename only
models.py            Pydantic models (RenameConfig, RenameResult, SolutionInfo)
renamer.py           Core renaming logic (detection, content replace, folder rename, ZIP)
visualizer.py        Solution ZIP parser → Markdown + Mermaid report segments
validator.py         Instruction validator — rule engine + model best-practice loader
rxconfig.py          Reflex app config
best_practices/      Per-model best-practice Markdown files (gpt41.md, gpt5chat.md, o3.md …)
web/
  state.py           Reflex state (upload, rename, visualise, validate, download)
  components.py      UI components (upload area, info panels, visualisation, validation)
  web.py             Page definitions, tab layout, and Reflex app setup
```

---

## Configuration

| Variable | Default | Description |
|---|---|---|
| `REFLEX_ENV` | `dev` | `dev` = two ports, `prod` = single-port mode |
| `FRONTEND_PORT` | `3000` | Frontend port (dev only) |
| `BACKEND_PORT` | `8000` | Backend port (dev only) |
| `PORT` | `2009` | Port for prod single-port mode |

---

## Deployment (Docker / Coolify)

```bash
docker build -t pp-agent-toolkit .
docker run -p 2009:2009 -e REFLEX_ENV=prod -e PORT=2009 pp-agent-toolkit
```

---

## Development

```bash
uv sync
uv run ruff check .
uv run ruff format .
uv run reflex run
```

---

## How schema names are derived

Power Platform bot schema names follow the pattern `{namespace}_{publisher_prefix}_{logical_name}`,  
e.g. `copilots_new_prefix_botname`.

The tool extracts the prefix (first two underscore-separated segments, e.g. `copilots_new_`) and appends a sanitized version of your new agent display name:

```
"My New Bot"  →  copilots_new_my_new_bot
"My Copy"     →  copilots_new_my_copy
```

You can override this with `--schema` (CLI) or by editing the derived schema preview field.

---

## Caveats

- The rename tool performs **text replacement** on all XML, JSON, and YAML (`data`) files; binary files (e.g. `.xlsx` knowledge files) are skipped automatically.
- Always test-import into a **development environment** before using in production.
- This tool does not update any **GUIDs** inside the solution — Power Platform generates new GUIDs on import, so this is not required.
- Instruction validation uses **static rule checks** (length, pattern matching, keyword detection). It does not call any external AI API.
- Validation is supported for **GPT-4.1 and higher** models only; agents using GPT-4o or earlier receive a "below assessment threshold" notice.
