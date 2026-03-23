# Cloud Coding Agent Instructions (Deployment-Focused)

This file defines how a cloud GitHub Copilot coding agent should operate in this repository.

## Mission

Deploy the PP Agent Toolkit solution to Azure safely and predictably.

## Workflow Scope

- Keep deployment automation in `.github/workflows/deploy-nightly.yml`.
- Keep `.github/workflows/copilot-setup-steps.yml` because the `copilot-setup-steps` job is required for Copilot coding-agent setup.
- Do not create or restore non-deployment workflows unless explicitly requested.

## Required Repo Knowledge

- `main.py`: Typer CLI entrypoint (`--inspect`, rename, and fetch flows).
- `renamer.py`: secure ZIP rename engine; keep untrusted input protections in place.
- `yaml_utils.py`: call `sanitize_yaml()` before parsing Power Platform YAML.
- `remote_fetch.py`: centralized auth/token logic. Never duplicate secret handling elsewhere.
- `toolkit/mcs/`: canonical parser/timeline/renderer implementations.
- Top-level `mcs_*.py` wrappers: preserve them. Tests monkeypatch private helpers in these files.

## Security And Safety Rules

- Use `defusedxml` for XML parsing. Never switch to stdlib XML parsers.
- Never log or print secrets or tokens.
- Do not weaken checks in `solution_checker.py` or `solution_checks.yaml`.
- Preserve `--inspect` behavior in CLI (must work without rename args).

## Mandatory Pre-Deploy Checklist

Run all commands and require success before deployment:

```bash
uv sync
uv run ruff check .
uv run ruff format --check .
uv run pytest tests/ -v --tb=short
uv run pip-audit --strict
uv run bandit -r .
```

If any step fails, fix the issue before deployment or record an explicit, reviewed exception.

## Azure Deployment Execution Rules

- Use `.github/workflows/deploy-nightly.yml` with `workflow_dispatch` for controlled releases.
- Keep preflight secret validation intact.
- Keep ACR build and Container App health checks intact.
- Prefer OIDC-based auth (`azure/login`) and avoid long-lived deployment credentials.

## Pull Request Behavior For Cloud Agents

- Keep changes minimal and deployment-focused.
- Do not refactor unrelated modules during deployment tasks.
- Validate tests after touching files used by wrappers or parser/rendering logic.
- Update docs when automation behavior changes.
