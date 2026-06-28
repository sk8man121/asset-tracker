# asset-tracker

**Personal side-project + income registry.** A local-first, stdlib-only Python tool that catalogs every project (software, music, creative, content, physical, service), tracks every income channel, and computes MRR, ROI, YTD revenue, per-platform fee burn, and time-to-income for each.

## What it does

- **Project registry** — `software / music / creative / content / physical / service`, status (`active / dormant / archived / idea`), tech stack, repo location, time-to-first-income.
- **Income channels** — `recurring / one_time / royalty / tip`, per-channel fee rules (`fee_pct + fee_flat`), per-platform grouping.
- **Transactions** — gross / fee / net, idempotent on `(channel_id, external_id)`, refunds supported.
- **Time logs** — minutes spent per project → revenue-per-hour ROI.
- **Metrics engine** — MRR (last-30d recurring), ARR, YTD, total, period fees, per-platform breakdown, per-project ROI, time-to-income, daily trend.
- **TUI dashboard** — 6 panels: top metrics, by platform, by project, active channels, recent tx, time-to-income. ANSI color, terminal-width-adaptive.
- **Backups** — `sqlite3.Connection.backup()` (crash-safe), rotation to keep N most recent.
- **Export** — JSON (full DB) and CSV (filtered txns / projects).
- **Integration framework** — connectors for Stripe, Gumroad, Bandcamp, GitHub Sponsors, Etsy. Live fetch is gated behind `AT_LIVE_INTEGRATIONS=1` (default off). Synthetic imports via `import-mock`.

## Quickstart

```bash
# Install (editable, optional — or just PYTHONPATH=src)
cd /Users/openclaw/hermes-data/projects/asset-tracker
PYTHONPATH=src python3 -m asset_tracker.cli --help

# Seed the DB with realistic sample data (5 projects, 7 txns, 4 time logs)
PYTHONPATH=src python3 -m asset_tracker.cli seed

# View the dashboard
PYTHONPATH=src python3 -m asset_tracker.cli dashboard

# One-line summary
PYTHONPATH=src python3 -m asset_tracker.cli summary

# Add your own project
PYTHONPATH=src python3 -m asset_tracker.cli project add my-app \
    --name "My App" --category software --tech-stack "python,fastapi"

# Add an income channel (Gumroad, 10% fee)
PYTHONPATH=src python3 -m asset_tracker.cli channel add \
    --project my-app --name "Gumroad MRR" \
    --platform gumroad --kind recurring --fee 10

# Log a transaction (fee auto-computed from channel rules)
PYTHONPATH=src python3 -m asset_tracker.cli tx log \
    --project my-app --channel 1 --gross 100 --kind recurring
```

## Commands

```
asset-tracker project add <id> --name <name> [--category ...] [--status ...]
asset-tracker project list [--status active] [--category software]
asset-tracker project show <id>
asset-tracker project update <id> [--name X] [--status dormant] ...
asset-tracker channel add --project <id> --name <n> --platform gumroad --kind recurring [--fee 10]
asset-tracker channel list [--project <id>]
asset-tracker tx log --project <id> --channel <id> --gross 100 --kind recurring [--external stripe_evt_X]
asset-tracker tx list [--project X] [--since 2026-01-01] [--until 2026-12-31] [--kind recurring]
asset-tracker metrics [--project X] [--period 30d|90d|ytd|all]
asset-tracker dashboard
asset-tracker summary                                # one-line: counts + MRR/ARR/YTD/total
asset-tracker backup [--keep 7]
asset-tracker export [path.json]
asset-tracker export-csv tx <path.csv> [--project X] [--since ...] [--until ...]
asset-tracker export-csv projects <path.csv> [--status active]
asset-tracker integrations                           # list connector stubs
asset-tracker import-mock <platform> [--count 5]    # synthetic import (Stripe / Gumroad / etc)
asset-tracker seed [path.json]                       # idempotent load
```

## Data model

See `docs/data-model.md`. Four tables:

- `projects` — registry of every venture
- `income_channels` — recurring/one-time income sources per project
- `transactions` — money-in events (idempotent on `(channel_id, external_id)`)
- `time_logs` — minutes invested per project (feeds ROI)

Schema is in `schema/schema.sql`. Versioning in `schema_meta` table.

## Storage

- **DB:** SQLite, single file at `./data/asset-tracker.db` (override via `AT_DB_PATH`).
- **Backups:** `./data/backups/asset-tracker-<timestamp>.db` (rotation to keep N).
- **Exports:** JSON + CSV.
- **Stdlib-only:** no external deps.

## Tests

```bash
PYTHONPATH=src python3 tests/test_basics.py    # 10 tests
PYTHONPATH=src python3 tests/test_edges.py     # 16 tests (validation, concurrency, extremes)
```

**26/26 tests passing.** Run on any commit before declaring "done."

## Integration connectors

Each connector normalizes platform-specific shapes into `NormalizedTxn`:

```python
from asset_tracker.integrations import REGISTRY, import_mock

# Synthetic import (no live API):
inserted, skipped = import_mock(conn, "stripe", count=5)

# When ready for live data, set AT_STRIPE_API_KEY and call fetch_recent():
# Set AT_LIVE_INTEGRATIONS=1 to opt in (default: stubs only).
```

Connectors: Stripe (subscriptions + charges), Gumroad (memberships + sales), Bandcamp (sales + tips), GitHub Sponsors, Etsy.

## Sprint ledger

This project was built via a 12-sprint RALPH loop (each ~30 min). Per-sprint evidence in `.ralph_loop_state`.

## License

Personal use. Adapt freely.
