# Release Notes - v0.3.0

## Summary
Version 0.3.0 focuses on dependency analysis, readability, and UX improvements across the web app and report output.

## Highlights

### New: Dependencies analysis experience
- Added a dedicated **Dependencies** workflow for solution ZIPs.
- Added **Aggregated** and **Detailed** diagram modes.
- Added explicit diagram controls and improved viewport behavior for large graphs.
- Improved handling of large dependency sets and label readability.

### New: Components and relations exploration
- Added a **Dependency Relations** table with:
  - filtering/search
  - sortable columns
- Added a **Components In Solution** table with:
  - filtering/search
  - sortable columns
  - sticky header
  - improved truncation + hover readability

### Improved: Component discovery and type coverage
- Dependency analysis now merges data from multiple sources, not only `solution.xml`:
  - `botcomponents/`
  - `bots/`
  - `Assets/*set.xml`
  - `Workflows/`
- Added explicit assets-based relation rows (workflows, connection references, environment variables, AI models).
- Improved type mapping and schema-based inference for botcomponent categories.
- Normalized long schema-based names to human-readable short names (for example `...topic.ConversationStart` -> `ConversationStart`).

### Improved: Analyse report readability
- Refined **Knowledge Sources & External Tools** section:
  - clearer item formatting
  - friendlier source labels
  - cleaner naming and status wording
- Refined **Topic & Trigger Audit** section:
  - overview summary
  - clearer conflict/orphan/guardrail entries

### Architecture and maintainability
- Consolidated MCS implementation under `toolkit/mcs/` with compatibility wrappers retained.
- Reduced duplicated logic between Visualize and Analyse paths.

## Documentation
- Updated `README.md` with:
  - current version reference
  - Dependencies feature overview
  - updated project structure and flow guidance

## Quality checks
- Lint: `uv run ruff check .` passed.
- Tests: `uv run pytest -q` passed (`64 passed`).

## Upgrade notes
- Project version updated to **0.3.0** in `pyproject.toml`.
- No external migration steps required.
