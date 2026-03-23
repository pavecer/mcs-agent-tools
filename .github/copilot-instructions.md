# PP Agent Toolkit — Workspace Instructions

## Build & Test

```bash
# Install dependencies
uv sync

# Run web UI (opens at http://localhost:3000)
uv run reflex run

# CLI rename
uv run python main.py solution.zip --agent-name "My Bot" --solution-name "MyBot"

# CLI inspect-only (no rename args required)
uv run python main.py solution.zip --inspect

# CLI remote fetch
uv run mcs-tools --env <envID> --agent <agentID-or-name> --fetch

# Run all tests
uv run pytest tests/

# Run a single test file
uv run pytest tests/test_renamer.py
```

> Use `uv run pytest` — plain `pytest` may not be in PATH.

## Architecture

| Layer | Key Files | Responsibility |
|-------|-----------|----------------|
| CLI | `main.py` | Typer entry point; `--inspect` / `--fetch` / rename flows |
| Core | `renamer.py`, `models.py` | ZIP rename engine; Pydantic data models |
| Analysis | `validator.py`, `solution_checker.py` | Instruction validation; 5-category solution health checks |
| Snapshot / Transcript | `toolkit/mcs/` | Parsing, timeline, rendering for snapshot ZIPs and transcript JSON |
| UI | `web/web.py`, `web/components.py` | Reflex state-driven single-page app; tab system |
| Utilities | `yaml_utils.py`, `remote_fetch.py` | Shared YAML sanitizer; Dataverse / PAC remote retrieval |

**Backward-compat wrappers**: `mcs_*.py` (top-level) are thin wrappers over `toolkit/mcs/`. Keep them — tests monkeypatch their private helpers (e.g., `mcs_renderer._check_public_url`). Do not delete or merge them.

**App metadata** (version, GitHub links, license) lives in `app_meta.py` — reuse it; don't hard-code.

## Conventions

- **Python ≥ 3.12**; full PEP 484 type annotations everywhere; use `str | None` union syntax.
- **Ruff** enforces formatting; line length = 120.
- **Pydantic v2** for all data models. Field validators enforce naming constraints.
- **XML parsing**: always use `defusedxml` — never the stdlib `xml` module.
- **Logging**: use `loguru`; do not use `print()` or stdlib `logging` in core logic.
- **YAML**: always call `yaml_utils.sanitize_yaml()` before parsing Power Platform YAML (fixes tab indentation and `@`-prefixed key escaping).
- **Model naming**: analysis data models carry an `MCS` prefix (`MCSBotProfile`, `MCSTimelineEvent`, etc.).
- **Private symbols**: prefix with `_` (`_GUID_RE`, `_extract_strings`). Module-level compiled regex patterns are the norm.
- No root-level `__init__.py`; use direct imports from sibling modules.

## UI Pitfalls

- `card()` already sets `padding` — do **not** pass `padding=` at call sites (causes a Reflex duplicate keyword arg crash).
- Frontend runs on port **3100** in container (not 3000) to avoid managed-runtime collisions. Nginx is gated on backend + frontend readiness before starting.

## CLI Pitfalls

- `--inspect` must work **without** `--agent-name` / `--solution-name` — do not add validation that requires those flags unconditionally.
- Typer CLI tests: assert `exit_code` for `BadParameter` paths; `CliRunner` output can be empty for parameter errors.

## Testing Patterns

- Instantiate Pydantic models directly in test setup — no fixtures needed for model-only tests.
- Monkeypatching targets the top-level `mcs_*.py` wrappers, not `toolkit/mcs/` internals.
- Test files in `tests/`; pytest discovers them automatically.

## Local Validation (Before Every Commit)

**All security checks run locally first** — GitHub Actions is a backup only, not a blocker.

### Setup (one-time)

```bash
# Install pre-commit framework
pip install pre-commit

# Install git hooks into .git/hooks
cd /Users/pavelvecer/GitHubRepos/pp-agent-renamer
pre-commit install

# (Optional) Run file validation checks manually
pre-commit run --all-files
```

### Pre-commit Workflow (automatic on `git commit`)

After `pre-commit install`, these basic checks **automatically run before each commit**:
- **File validators** — YAML/JSON/TOML syntax, merge conflicts
- **Trailing whitespace** — clean line endings
- **End-of-file fixers** — consistent file endings

For comprehensive validation (Ruff, tests, security), use the manual approach below.

### Manual Validation (comprehensive - run before pushing)

```bash
# Run FULL validation suite (all security + code quality checks)
bash scripts/validate-local.sh

# This runs:
# 1. Ruff linter — code style and import sorting
# 2. Ruff formatter — consistent formatting (line length = 120)
# 3. Pytest — all unit tests
# 4. pip-audit — CVE vulnerability check
# 5. Bandit — security issue scanning

# Or run individual checks:
uv run ruff check .                    # Lint only
uv run ruff format .                   # Format (auto-fix)
uv run pytest tests/ -v                # Tests only
uv run pip-audit --strict              # CVE check
uv run bandit -r .                     # Security linting
```

### Workflow Summary

| Stage | Trigger | What Runs | Auto-fix? |
|-------|---------|-----------|-----------|
| **Pre-commit** | `git commit` | File syntax validators | Yes (whitespace, EOL) |
| **Local validation** | `bash scripts/validate-local.sh` | Ruff + tests + security | Ruff only |
| **GitHub CI** | PR to `main` | Full suite (backup only) | No |

### Common Fixes

| Issue | Fix |
|-------|-----|
| Ruff lint errors | `uv run ruff check . --fix` |
| Format issues | `uv run ruff format .` |
| Test failures | `uv run pytest tests/ -v` (debug, then fix code) |
| CVE alerts | Update `pyproject.toml` dependency versions |
| Bandit false positives | Review and update `.bandit` exclusions |

### When to Bypass Pre-commit (Rare)

```bash
# Only when absolutely necessary (e.g., WIP branch, emergency fix):
git commit --no-verify
# ⚠ Use sparingly — always run bash scripts/validate-local.sh before final push.
```

## Security Requirements

- All ZIP/XML/YAML from uploaded files is untrusted input — use `defusedxml` and validate before processing.
- `solution_checker.py` runs injection-pattern and hardcoded-credential scans; do not weaken those checks.
- Never log or print secret/token values; `remote_fetch.py` holds auth logic — keep credentials out of other modules.

## Cloud Coding Agent Rules (Azure Deployment Scope)

- Repository automation is deployment-focused. Keep only deployment-related workflows under `.github/workflows/` plus the required Copilot setup workflow.
- Keep `.github/workflows/deploy-nightly.yml` as the only Azure deployment pipeline unless explicitly asked to add another deployment target.
- Keep `.github/workflows/copilot-setup-steps.yml` because its `copilot-setup-steps` job is required for Copilot coding-agent environment setup.
- Do not reintroduce non-deployment workflows (for example docs/presentation publishing or generic CI safety-net pipelines) unless explicitly requested.

### Mandatory Pre-Deploy Validation Checklist

Run this checklist before triggering deployment or preparing deployment-related changes:

```bash
uv sync
uv run ruff check .
uv run ruff format --check .
uv run pytest tests/ -v --tb=short
uv run pip-audit --strict
uv run bandit -r .
```

- Deployment changes are incomplete unless all checklist commands pass or failures are intentionally approved with a documented reason.
- Treat local validation as mandatory ownership now that non-deployment CI workflows are intentionally removed.
