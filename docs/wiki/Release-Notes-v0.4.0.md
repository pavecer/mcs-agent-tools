# Release Notes v0.4.0

Version 0.4.0 introduces eval fit analysis and optional eval generation/export workflows for Copilot Studio solution ZIPs.

## What is new

### Evals fit analysis
- Added an Evals workflow for agent solution ZIPs.
- Added a composite fit score for existing built-in test cases and evaluation rows.
- Added visible fit dimensions for topic coverage, instruction alignment, tools/grounding coverage, and case quality.
- Added surfaced gap summaries and recommendations.

### Optional eval generation and improvement
- Added optional Generate Sample Evals action.
- Added optional Improve Current Evals action when the current eval fit score is below 50%.
- Added deterministic scenario generation from instructions, topics, trigger queries, guardrails, and knowledge/tool hints.
- Added preview tables for generated and improved cases before export.

### Export support
- Added export of a generated/improved solution copy with injected `mspva_*` testing assets.
- Added support for writing test sets, test cases, evaluation sets, and evaluation rows back into solution structure.

### Evals UX improvements
- Expanded the Evals tab with fit scorecards, top-gap summaries, recommendations, preview counts, and export/download actions.
- Kept generation, improvement, and export explicit and user-triggered.

## Technical updates
- Added a dedicated eval-management backend module.
- Added targeted tests for fit analysis, deterministic preview generation, and export round-trip parsing.
- Fixed Reflex compile/runtime issues during the new Evals UI rollout.

## Quality checks
- Lint passed: `uv run ruff check .`
- Tests passed: `uv run pytest -q` (`76 passed`)
- Format check passed: `uv run ruff format --check .`

## Version
- Updated project version to `0.4.0` in `pyproject.toml`.
