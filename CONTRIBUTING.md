# Contributing to asset-tracker

Thanks for helping improve this personal income-tracking CLI.

## Principles

- **Stdlib only** — no new runtime dependencies in `pyproject.toml`
- **Local-first** — SQLite on disk; no required network except optional live imports
- **Small diffs** — match existing module style and naming

## Development setup

```bash
git clone https://github.com/sk8man121/asset-tracker.git
cd asset-tracker
pip install -e .
export PYTHONPATH=src
```

## Running tests

Tests use a lightweight harness (no pytest required):

```bash
PYTHONPATH=src python3 tests/test_basics.py
PYTHONPATH=src python3 tests/test_edges.py
PYTHONPATH=src python3 tests/test_daily.py
PYTHONPATH=src python3 tests/test_integrations.py
```

CI runs all four on Python 3.9 and 3.12.

## Branch naming

Use descriptive branch names, e.g. `cursor/feature-description-b61c` for cloud agent work.

## Adding a platform connector

1. Subclass `Connector` in `src/asset_tracker/integrations.py`
2. Implement `normalize()` and `_fetch_recent_impl()` (or document why live fetch is unavailable)
3. Register in `REGISTRY`
4. Add env var to `.env.example`
5. Add mocked fixture + test in `tests/test_integrations.py`

## Pull requests

Fill out the PR template checklist and keep docs (`README.md`, `docs/handover.md`) in sync when behavior changes.
