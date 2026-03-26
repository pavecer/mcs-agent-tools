# PP Agent Toolkit

Toolkit for **Power Platform / Copilot Studio** exports with a single Reflex web UI plus a rename-focused CLI.

## Current Version

- **0.4.0**

Release notes:

- [Root release notes](/Users/pavelvecer/GitHubRepos/pp-agent-renamer/RELEASE_NOTES_v0.4.0.md)
- [Wiki release notes](/Users/pavelvecer/GitHubRepos/pp-agent-renamer/docs/wiki/Release-Notes-v0.4.0.md)

## What The Solution Offers

### 1. Visualize (solution ZIP or snapshot ZIP)

Generate markdown sections and Mermaid diagrams for agent structure.

- Bot profile and AI settings
- Components/topics table
- Topic redirect graph (`BeginDialog` relationships)

### 2. Validate Instructions

Run static, rule-based instruction validation against model-specific best-practice files in `best_practices/`.

Supported model families include:

- `gpt41`, `gpt41mini`, `gpt41nano`
- `gpt5`, `gpt5chat`
- `o1`, `o3`, `o4mini`

Output is rule-by-rule with `PASS`, `WARN`, or `FAIL`, plus optional rendered best-practice guidance.

### 3. Check (solution ZIP only)

Run a Copilot Studio-specific solution check — similar to Power Platform's built-in Solution Checker but focused on agent quality, configuration, and security.

Checks are grouped into five categories:

- **Solution** — `solution.xml` validity, publisher prefix, version, description
- **Agent** — content moderation level, knowledge grounding, recognizer type, auto-publish setting
- **Topics** — system topic completeness, inactive topics, empty dialogs, topic count
- **Knowledge** — presence of knowledge sources, file sizes, semantic search, web browsing
- **Security** — prompt injection patterns, hardcoded credentials, file upload analysis

Results are shown with `PASS`, `WARN`, `FAIL`, and `INFO` severity and can be filtered by category.

### 4. Analyse Copilot Studio Snapshot + Transcript

For snapshot ZIPs (containing `botContent.yml`), the app provides deeper analysis sections:

- Profile
- Topics/components
- Topic graph
- Conversation analysis

The Analyse output emphasizes readability and operations-focused reporting:

- Human-readable **Knowledge Sources & External Tools** summaries
- Human-readable **Topic & Trigger Audit** with overview, conflicts, orphans, and guardrails
- Cleaner naming that removes noisy schema prefixes where possible

You can also upload transcript JSON and render a detailed conversation report with:

- Sequence diagram
- Execution timeline/gantt-style sections
- Event log and error highlights

**Direct Dataverse transcript retrieval (NOT YET IMPLEMENTED):**

Planned feature for Analyse tab to fetch transcripts directly by transcript ID without manual JSON export:
- Enter environment + transcript ID
- Authenticate via environment credentials (recommended) or manual token/service principal fields
- Fetch and render conversation analytics without exporting JSON manually

_This feature is currently in development and will be available in a future release._

### 5. Dependencies (solution ZIP)

Analyze dependency health and component inventory for both agent and non-agent solution exports.

Includes:

- Aggregated and detailed dependency diagram modes
- Diagram zoom controls (`-`, `+`, reset) with scroll support
- Relations table with sorting and filtering
- Components table with sorting, filtering, sticky header, and truncation/hover details
- Discovery merged from `solution.xml` and artefact folders (`botcomponents/`, `bots/`, `Assets/*set.xml`, `Workflows/`)

### 6. Evals Fit + Optional Generation (solution ZIP only)

The Evals tab now analyses how well existing built-in test cases and evaluation rows fit the agent purpose based on:

- System instructions and behavioural constraints
- Active topics and trigger coverage
- Knowledge-search and tool-enabled flows
- Guardrail/system-topic coverage
- Eval density, duplication, and assertion quality

What it provides:

- Composite fit score with transparent sub-scores
- Coverage gaps and recommendations
- Optional **Generate Sample Evals** action for solutions with missing or weak eval coverage
- Optional **Improve Current Evals** action when existing eval fit drops below 50%
- Optional export of a modified solution ZIP with generated/improved `mspva_*` eval assets injected

Notes:

- Generation and improvement are **not automatic**.
- Export is explicit and button-triggered.
- The current implementation uses deterministic generation with room for optional LLM-assisted expansion later.

### 7. Rename (solution ZIP only)

Create a safe copy of an exported solution by rewriting bot and solution identifiers so import does not overwrite the original.

What is updated:

- Bot schema name references (for example `copilots_new_my_bot` -> derived or overridden new schema)
- Agent display name (`bot.xml`, `gpt.default/botcomponent.xml`)
- Solution unique name (`solution.xml` + text references)
- Solution display name (`solution.xml` localized name)
- Folder names: `bots/{schema}` and `botcomponents/{schema}.*`

## Supported Inputs

- **Power Platform solution ZIP** (contains `bots/`)
- **Copilot Studio snapshot ZIP** (contains `botContent.yml`)
- **Transcript JSON** (for conversation analysis in Analyse flow)

## Quick Start

### Web UI

```bash
uv sync
uv run reflex run
```

Open `http://localhost:3000`.

Typical flow:

1. Upload a `.zip` export.
2. For solution ZIPs, use **Dependencies** first for component/dependency health, then **Visualize**, **Validate**, **Check**, and **Evals**.
3. For snapshot ZIPs, use **Analyse**, **Visualize**, and **Validate** tabs.
4. Optionally upload transcript `.json` in Analyse to enrich conversation reporting.
5. In **Evals**, optionally generate or improve sample evals and export a solution copy that includes them.
6. Use the **Rename** tab (solution ZIPs only) last to create a renamed copy for safe import.

### CLI (rename)

```bash
uv sync

# Rename from ZIP
uv run python main.py solution.zip \
    --agent-name "My New Bot" \
    --solution-name "MyNewBot"

# Rename from extracted folder
uv run python main.py ./MySolutionFolder \
    --agent-name "My Bot Copy" \
    --solution-name "MyBotCopy"

# Override derived schema name
uv run python main.py solution.zip \
    -a "My Bot Copy" -s "MyBotCopy" \
    --schema copilots_new_my_bot_copy

# Custom output ZIP path
uv run python main.py solution.zip \
    -a "My Bot Copy" -s "MyBotCopy" \
    -o ./output/MyBotCopy.zip
```

Inspect-only mode example:

```bash
uv run python main.py solution.zip --inspect
```

### CLI (remote fetch and analysis)

You can fetch bot content directly from an environment and generate an analysis report without manual ZIP exports.

Example (acceptance criteria):

```bash
uv run mcs-tools --env <envID> --agent <agentID-or-name> --fetch
```

This command will:

1. Resolve the target agent by ID or name.
2. Fetch the latest bot content from the environment.
3. Optionally fetch recent transcripts (best-effort).
4. Generate a Markdown analysis report in the working directory.

Useful options:

```bash
# Explicit provider selection: auto | pac | dataverse
uv run mcs-tools --fetch --env <envID> --agent "Legal Copilot" --provider pac

# Save report to a custom path
uv run mcs-tools --fetch --env <envID> --agent <agentID> --report-output ./reports/legal.md

# Disable transcript fetch
uv run mcs-tools --fetch --env <envID> --agent <agentID> --no-transcripts

# Dataverse API mode
uv run mcs-tools --fetch --provider dataverse --env https://<org>.crm.dynamics.com --agent <agentID>
```

Fallback behavior:

- If remote fetch is unavailable or authentication is missing, the tool prints a clear error and guidance.
- You can always fall back to manual local input (`solution.zip`, snapshot ZIP, or transcript JSON upload in the web UI).

## Configuration

Environment variables:

- `REFLEX_ENV`: `dev` (default) or `prod`
- `FRONTEND_PORT`: frontend port in dev mode (default `3000`)
- `BACKEND_PORT`: backend port in dev mode (default `8000`)
- `PORT`: single port in prod mode (default `2009`)
- `API_URL`: public app URL baked into the frontend during production image build (default `http://localhost:2009` for local Docker)
- `USERS`: optional basic auth credentials list (`user1:pass1,user2:pass2`)

Remote fetch credentials and connection setup:

- `MCS_DATAVERSE_URL`: Dataverse base URL (for API mode), for example `https://contoso.crm.dynamics.com`
- `MCS_DATAVERSE_TOKEN`: Bearer token for Dataverse API access
- `MCS_AAD_TENANT_ID`: Entra tenant ID (service principal flow)
- `MCS_AAD_CLIENT_ID`: Entra app client ID (service principal flow)
- `MCS_AAD_CLIENT_SECRET`: Entra app client secret (service principal flow)
- `MCS_AAD_SCOPE`: Optional OAuth scope override (defaults to `<dataverse-url>/.default`)
- `MCS_ADMIN_SESSIONS_URL`: Optional admin analytics sessions API endpoint (transcript fallback)
- `MCS_ADMIN_API_TOKEN`: Optional bearer token for admin analytics API

Notes:

- Do not hardcode secrets in source code or command history.
- Prefer environment variables for tokens and client secrets.
- Transcript retrieval is best-effort and may be constrained by retention windows (commonly around 29 days in Copilot Studio transcript analytics).

Power Platform CLI setup (recommended for fetch mode):

```bash
# Ensure pac is installed and available
pac --version

# Authenticate
pac auth create

# (Optional) verify accessible copilots
pac copilot list
```

When `USERS` is set, the app requires login at `/login`.

## Development

```bash
uv sync
uv run ruff check .
uv run ruff format .
uv run pytest
uv run reflex run
```

## Sanity Checks

Recommended quick validation before commit:

```bash
uv run ruff check .
uv run pytest -q
```

Architecture sanity:

- Shared YAML pre-processing is centralised in `yaml_utils.py` (used by both snapshot and solution parsers).
- App metadata (repository links, version resolution, license label) is centralised in `app_meta.py`.
- Avoid introducing duplicate parser helpers in feature modules; prefer shared utilities when behavior is reused.

## Project Structure

```text
main.py              CLI entry point (Typer + Rich)
app_meta.py          Shared app metadata (version, links, license label)
yaml_utils.py        Shared YAML preprocessing helper
renamer.py           Rename engine + safe ZIP handling
models.py            Pydantic models for rename config/results
visualizer.py        Solution ZIP parser to markdown/mermaid segments
deps_analyzer.py     Dependency analysis + diagram + relations/component tables
validator.py         Model-aware instruction validation
toolkit/mcs/         Canonical snapshot analysis package
web/state.py         Reflex app state and workflows
web/components.py    UI components
web/mermaid.py       Mermaid runtime support + diagram viewport behavior
web/web.py           App pages and tab routing
best_practices/      Validation rule reference docs per model family
tests/               Unit tests
```

## Caveats

- Rename is string-based across selected text files (`.xml`, `.json`, `.yaml`, `.yml`, known extensionless `data` files).
- Binary files are not rewritten.
- GUIDs are not regenerated by this tool.
- Validation is static/rule-based and does not call an LLM API.
- Eval generation and improvement are optional, deterministic in the current implementation, and only modify a solution when you explicitly export a generated/improved copy.
- Test coverage currently focuses on renamer utilities and validation of naming rules.

## License

This repository is licensed under the MIT License. You are free to use, modify, and redistribute this project under the license terms.
