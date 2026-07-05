# asset-tracker

**Personal side-project + income registry.** A local-first, stdlib-only Python CLI that catalogs every project you work on, tracks income channels, logs transactions and time, and shows MRR, ROI, and per-platform breakdowns in a terminal dashboard.

Built for daily use — not a demo, not a scaffold.

## Install

```bash
git clone https://github.com/sk8man121/asset-tracker.git
cd asset-tracker
pip install -e .
```

Or without install:

```bash
export PYTHONPATH=src
python3 -m asset_tracker.cli --help
```

Optional: copy `.env.example` to `.env` and set `AT_DB_PATH` if you want the database somewhere other than `./data/asset-tracker.db`.

## First run

```bash
asset-tracker init
```

The wizard creates your first project and income channel, saves defaults to `data/.asset-tracker.json`, and tells you what to do next.

To explore with demo data first:

```bash
asset-tracker init --seed
asset-tracker dashboard
```

## Daily workflow

This is the routine the tool is designed around:

```bash
# Morning check-in (10 seconds)
asset-tracker summary
asset-tracker dashboard

# Log income as it happens
asset-tracker log 49.99
asset-tracker log 29.00 --notes "book sale"

# Log time for ROI tracking
asset-tracker time log --minutes 90 --notes "feature work"

# Weekly safety net
asset-tracker backup
asset-tracker recent          # last 7 days at a glance
```

With defaults configured (via `init` or `config set`), `log` needs only the amount. Channel names work instead of numeric IDs:

```bash
asset-tracker log 100 --channel gumroad
```

### Stripe import (optional)

```bash
# In .env: AT_STRIPE_API_KEY=sk_live_... and AT_LIVE_INTEGRATIONS=1
asset-tracker import stripe --since 30d
```

## Commands

### Essentials

| Command | What it does |
|---|---|
| `init` | First-run wizard (or `--seed` for demo data) |
| `log <amount>` | Quick income log using config defaults |
| `summary` | One-line morning check-in |
| `dashboard` | Full 6-panel TUI view |
| `recent` | Last N days of transactions + time |
| `doctor` | Health check + setup guidance |
| `backup` | Crash-safe SQLite snapshot |

### Projects & channels

```
asset-tracker project add <id> --name <name> --category software
asset-tracker project list [--status active]
asset-tracker project show <id>
asset-tracker channel add --project <id> --name "Gumroad" --platform gumroad --kind recurring --fee 10
asset-tracker channel list [--project <id>]
```

### Transactions & time

```
asset-tracker tx log --project <id> --channel gumroad --gross 100 --kind recurring
asset-tracker tx list [--project X] [--since 2026-01-01]
asset-tracker time log --minutes 90 [--project X] [--notes "..."]
asset-tracker time list [--project X]
```

`--channel` accepts a numeric id, channel name, or platform name (when unambiguous).

### Metrics & export

```
asset-tracker metrics [--period 30d|90d|ytd|all]
asset-tracker export [path]                    # full JSON dump
asset-tracker export-csv tx out.csv            # CSV export
asset-tracker config show                      # view defaults
asset-tracker config set --default-project my-app --default-channel gumroad
```

## What it tracks

- **Projects** — software, music, creative, content, physical, service
- **Income channels** — per-platform fee rules (Gumroad, Stripe, Bandcamp, GitHub Sponsors, Etsy, direct)
- **Transactions** — gross / fee / net, idempotent on `(channel_id, external_id)`, refunds supported
- **Time logs** — minutes per project → revenue-per-hour ROI
- **Metrics** — MRR (last 30d recurring), ARR, YTD, per-platform breakdown, time-to-first-income

## Storage

| Path | Purpose |
|---|---|
| `data/asset-tracker.db` | SQLite database (gitignored) |
| `data/.asset-tracker.json` | Your default project/channel (gitignored) |
| `data/backups/` | Rotating snapshots (keep 7 by default) |

## Tests

```bash
PYTHONPATH=src python3 tests/test_basics.py    # 10 tests
PYTHONPATH=src python3 tests/test_edges.py     # 17 tests
PYTHONPATH=src python3 tests/test_daily.py     # 10 tests — daily workflow
PYTHONPATH=src python3 tests/test_integrations.py  #  8 tests — platform imports
```

CI runs all 45 on push.

## Integration connectors

Five platform connectors ship with normalized import plumbing. Live API fetch requires `AT_LIVE_INTEGRATIONS=1` in `.env`:

| Platform | Live import | Env var |
|----------|-------------|---------|
| Stripe | Yes | `AT_STRIPE_API_KEY` |
| Gumroad | Yes | `AT_GUMROAD_ACCESS_TOKEN` |
| GitHub Sponsors | Yes | `AT_GITHUB_TOKEN` |
| Etsy | Yes | `AT_ETSY_API_KEY`, `AT_ETSY_SHOP_ID` |
| Bandcamp | No (no public sales API) | Use `import-mock` or manual `log` |

```bash
asset-tracker integrations
asset-tracker import stripe --since 30d --project my-saas
asset-tracker import gumroad --since 30d
asset-tracker import-mock stripe --count 10   # synthetic test data
```

Set `metadata.project_id` on Stripe charges, or pass `--project` to override. Optional config map in `data/.asset-tracker.json`:

```json
{ "import_project_map": { "unassigned": "my-saas" } }
```

## Architecture

```
CLI → repository → SQLite
         ↓
    metrics / dashboard / export
         ↓
    integrations (NormalizedTxn → idempotent import)
```

Zero external dependencies. Python ≥ 3.9. ~3,200 lines.

## License

MIT — personal tool, use freely.
