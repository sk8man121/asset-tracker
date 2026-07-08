# NEXT-AGENT.md — Wave 5+ backlog

**Current version:** 0.4.1 · **Tests:** 65 · **Constraint:** stdlib-only runtime

Wave 4 (this branch) shipped HTTP secret redaction, report/import bugfixes, metrics aggregation refactor, dashboard compare reuse, backup tests, `AT_LOG_LEVEL` wiring, and completion/docs sync.

Do **not** re-audit from scratch. Work the list below in order unless the user redirects.

## Ordered backlog

1. **Import safety**
   - Cap pagination loops (Stripe / Gumroad / Etsy) with a max page/iteration limit and optional short sleep between pages.
   - Stop auto-creating projects on unknown `project_id` unless `--create-projects` (or require `import_project_map` / `--project` only).
   - Files: [`src/asset_tracker/integrations.py`](../src/asset_tracker/integrations.py), CLI import flags in [`cli.py`](../src/asset_tracker/cli.py).

2. **HTTP resilience**
   - Retry on 429 / 5xx with exponential backoff in [`http.py`](../src/asset_tracker/http.py).
   - Add tests for timeout and `HttpError` body handling (token redaction already covered).

3. **Export completeness**
   - `list_transactions(limit=1000)` silently truncates CSV / list / dashboard paths.
   - Add `--all` / pagination, or warn when the result set was truncated.
   - Files: [`repository.py`](../src/asset_tracker/repository.py), [`csv_export.py`](../src/asset_tracker/csv_export.py), [`cli.py`](../src/asset_tracker/cli.py).

4. **GitHub Sponsors timing**
   - Prefer payout / charge date when the API provides it; today uses sponsorship `created_at` (inaccurate for revenue timing).
   - File: [`integrations.py`](../src/asset_tracker/integrations.py) `GitHubSponsorsConnector.normalize`.

5. **Test harness unify**
   - Extract shared `_record` / temp-db helpers into `tests/_harness.py`.
   - Cover populated `dashboard --compare` and `export-csv projects`.

6. **Dev extras (optional)**
   - Add `[project.optional-dependencies] dev` with pytest/ruff; keep `dependencies = []`.
   - Do not make pytest required for CI unless the user asks.

7. **Docs cleanup**
   - Archive or clearly mark historical [`RALPH.md`](../RALPH.md) / [`docs/state-after-sprint-6.md`](state-after-sprint-6.md) so they don’t contradict v0.4.x test counts.

8. **Product backlog (only if user asks)**
   - Multi-currency FX conversion
   - Tax categorization tags
   - Interactive (curses) TUI dashboard
   - Bandcamp live API (blocked: no public sales API)

## Verification baseline

```bash
PYTHONPATH=src python3 tests/test_basics.py
PYTHONPATH=src python3 tests/test_edges.py
PYTHONPATH=src python3 tests/test_daily.py
PYTHONPATH=src python3 tests/test_integrations.py
PYTHONPATH=src python3 tests/test_reporting.py
PYTHONPATH=src python3 tests/test_backup.py
pip install -e . && asset-tracker doctor
```

## Architecture reminder

```
CLI → repository → SQLite
         ↓
    metrics / dashboard / export / report
         ↓
    integrations (NormalizedTxn → idempotent import)
```

Live imports require `AT_LIVE_INTEGRATIONS=1` plus platform env vars (see `.env.example`).
