# Changelog

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
