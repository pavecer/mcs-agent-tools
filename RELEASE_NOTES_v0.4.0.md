# Release Notes - v0.4.0

## Summary
Version 0.4.0 introduces built-in eval fit analysis and optional eval generation workflows for Copilot Studio solution ZIPs, while tightening the Evals tab experience and solution export flow.

## Highlights

### New: Evals fit analysis
- Added an **Evals** analysis workflow for agent solution ZIPs.
- Added a composite fit score that estimates how well built-in test cases and evaluation rows align with the agent purpose.
- Added transparent fit dimensions across:
  - topic coverage
  - instruction alignment
  - tools and grounding coverage
  - case quality
- Added surfaced gaps and recommendations directly in the web UI.

### New: Optional eval generation and improvement
- Added optional **Generate Sample Evals** action in the Evals tab.
- Added optional **Improve Current Evals** action when existing eval fit is below 50%.
- Added deterministic scenario generation using:
  - system instructions
  - active topics and trigger queries
  - system-topic guardrails
  - knowledge-source and tool hints
- Added preview tables for generated and improved test cases and eval rows before export.

### New: Export solution with injected eval assets
- Added optional export of a modified solution ZIP containing generated or improved `mspva_*` testing assets.
- Added support for writing:
  - `TestSetDefinition`
  - `TestCaseDefinition`
  - `EvaluationSet`
  - `EvaluationData`
- Reused the existing safe ZIP extraction and packaging path so generated solution copies remain consistent with the rest of the app.

### Improved: Evals tab UX
- Expanded the Evals tab from a passive viewer into an action-oriented workspace.
- Added fit scorecards, top-gap summaries, recommendations, preview category counts, and export/download actions.
- Kept generation, improvement, and export explicitly button-triggered rather than automatic.

### Technical updates
- Added a dedicated eval-management backend module to keep analysis, generation, and export logic out of Reflex state handlers.
- Added targeted tests for:
  - fit-score analysis
  - deterministic preview generation
  - solution export and re-parse of injected eval assets
- Fixed Reflex compile/runtime issues introduced during the Evals UI expansion.

## Documentation
- Updated `README.md` with:
  - the new 0.4.0 version reference
  - Evals fit and optional generation workflow details
  - updated typical solution flow including the Evals tab

## Quality checks
- Lint: `uv run ruff check .` passed.
- Tests: `uv run pytest -q` passed (`76 passed`).
- Format: `uv run ruff format --check .` passed.

## Upgrade notes
- Project version updated to **0.4.0** in `pyproject.toml`.
- No migration steps are required for existing users.
- Eval generation and improvement remain optional and only modify a solution when you explicitly export a generated/improved copy.