# v0.4.0 Release Summary

## Short release description
v0.4.0 adds eval fit analysis and optional eval generation workflows for Copilot Studio solution ZIPs. The Evals tab can now assess how well built-in test cases align with an agent's purpose, highlight coverage gaps, preview generated or improved eval assets, and export a solution copy with injected `mspva_*` testing components.

## Highlights
- Added composite eval fit scoring for existing built-in test cases and evaluation rows.
- Added fit breakdown across topic coverage, instruction alignment, tools and grounding, and case quality.
- Added optional Generate Sample Evals and Improve Current Evals actions in the web UI.
- Added export of a generated/improved solution ZIP with injected eval assets.
- Added targeted backend tests for fit analysis, preview generation, and export round-trip parsing.
- Fixed runtime issues during the Evals tab rollout and aligned formatting/lint checks.

## PR description draft
This release expands the solution-analysis workflow with a new eval-management capability.

Main changes:
- new eval analysis backend for scoring existing eval fit against agent instructions, topics, tools, and guardrails
- deterministic preview generation for new or improved eval scenarios
- solution export path that injects generated `mspva_*` testing assets back into a solution ZIP
- Evals tab UX update with scorecards, gaps, recommendations, preview tables, and explicit export/download actions
- release documentation and version bump to `0.4.0`

Validation:
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run pytest -q` (`76 passed`)

## GitHub release notes draft
### What’s new
v0.4.0 introduces eval fit analysis and optional eval generation/export workflows for Copilot Studio solution ZIPs.

### Included in this release
- Evals tab fit analysis for built-in test cases and evaluation rows
- Optional generate/improve actions for eval coverage
- Export of a solution copy with injected eval assets
- Improved Evals tab UX and preview flow
- Backend/test/runtime hardening

### Quality checks
- Lint passed
- Format check passed
- Tests passed: `76 passed`
