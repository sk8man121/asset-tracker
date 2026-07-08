# Changelog

## 0.4.1 — 2026-07-08

### Hardening (Wave 4)

- **HTTP secret redaction** — `HttpError` strips `access_token` / API key query params from exception messages (Gumroad-safe)
- **Report delta** — clarified prior-zero percent handling (`new` / `n/a` labels)
- **Import auto-projects** — always use valid schema category `service` (removed dead `"other"` category check)
- **Metrics** — per-project aggregations via grouped queries instead of N× correlated subqueries
- **Dashboard `--compare`** — reuses `build_report` current-window metrics (no double compute)
- **`AT_LOG_LEVEL`** — wired to `logging.basicConfig` in CLI entry
- Bash completion covers `report`, `time`, `import csv|sync`, `export-csv`
- **`test_backup.py`** — snapshot, rotation, JSON export, seed idempotency (+6 tests → **65 total**)
- Handoff doc: `docs/NEXT-AGENT.md`

## 0.4.0 — 2026-07-05

### Reporting & review (Wave 3)

- **`report`** — period summary with prior-window comparison (`--period month|quarter|30d|90d|ytd`)
- **`report --json`** — machine-readable report payload with deltas, highlights, sparkline
- **`export-csv rollup`** — monthly tax-year rollup by project/platform/currency
- **`recent`** — per-project net summary block
- **`dashboard --compare`** — period net delta vs prior window in top metrics panel
- **Doctor** — suggests `report --period month` when healthy with transactions
- Extended metrics periods: `month`, `quarter`; `tx_count` and `hours_logged` in metrics output

### Tests

- 59 tests total (+8)

## 0.3.0 — 2026-07-05

### Ingestion completion (Wave 2)

- **`import csv`** — bulk import from Bandcamp sales exports or generic CSV (round-trips with `export-csv`)
- **`import sync`** — fetch from all configured live platforms in one command
- **Doctor integrations section** — connector verify status, last sync timestamps, stale-sync tips
- **`last_sync` config** — tracks per-platform import timestamps in `.asset-tracker.json`

### Tests

- 51 tests total (+6)

## 0.2.2 — 2026-07-05

### Integrations and metrics

- **Gumroad, GitHub Sponsors, Etsy** live import (mocked tests included)
- **Bandcamp** documented as manual/`import-mock` only (no public sales API)
- **`import --project`** flag and `import_project_map` config for project remapping
- **`by_currency`** metrics grouping; dashboard/summary/recent show per-currency when mixed
- **Doctor** warns when `unassigned` project has imported transactions

### Docs and hygiene

- MIT `LICENSE` file
- Synced stale Ralph/README/integration docs
- GitHub issue/PR templates and `CONTRIBUTING.md`
- 45 tests total (+7)

## 0.2.0 — 2026-07-03

### Daily use productization

- **`init`** — guided first-run wizard with config defaults
- **`log <amount>`** — one-command income logging
- **`time log/list`** — track hours for ROI metrics
- **`doctor`** — health check with actionable guidance
- **`recent`** — weekly activity digest
- **`config show/set`** — persist default project/channel
- Channel resolution by name or platform (not just numeric IDs)
- Dashboard onboarding state for empty databases
- `.env` auto-loading from repo root
- **35 tests** + GitHub Actions CI

### Fixes

- `pyproject.toml`: declare `src` layout so `pip install -e .` works

## 0.2.1 — 2026-07-03

### Live integrations

- **Stripe live import** via stdlib `urllib` (`asset-tracker import stripe`)
- `integrations.verify()` pings Stripe when `AT_LIVE_INTEGRATIONS=1`
- Fixed auto-created import channels using wrong platform id
- **`recent`** command for weekly review
- **`tx log`** uses config defaults; `--kind` optional
- Bash completion script
- Integration tests with mocked Stripe API (38 tests total)

## 0.1.0 — 2026-06-28

Initial Ralph loop delivery: schema, CRUD, metrics, dashboard, backup, CSV export, integration stubs.
