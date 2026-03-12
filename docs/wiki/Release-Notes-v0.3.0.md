# Release Notes v0.3.0

Version 0.3.0 focuses on dependency analysis, readability, and UX improvements.

## What is new

### Dependencies analysis
- Added a dedicated Dependencies workflow for solution ZIPs.
- Added Aggregated and Detailed diagram modes.
- Improved large-diagram readability and viewport behavior.

### Dependency tables
- Added Dependency Relations table with search/filter + sorting.
- Added Components table with search/filter + sorting.
- Improved table readability with sticky header and truncation/hover details.

### Discovery and mapping improvements
- Analyzer now merges metadata from:
  - `solution.xml`
  - `botcomponents/`
  - `bots/`
  - `Assets/*set.xml`
  - `Workflows/`
- Added explicit assets-mapping relation rows.
- Improved botcomponent type inference and name normalization.

### Analyse readability improvements
- Knowledge Sources & External Tools section is now more human-readable.
- Topic & Trigger Audit section now includes clearer summaries and issue blocks.

## Technical updates
- MCS modules consolidated under `toolkit/mcs/` with compatibility wrappers retained.
- Reduced duplicate logic between Analyze/Visualize-related paths.

## Quality checks
- Lint passed: `uv run ruff check .`
- Tests passed: `uv run pytest -q` (`64 passed`)

## Version
- Updated project version to `0.3.0` in `pyproject.toml`.
