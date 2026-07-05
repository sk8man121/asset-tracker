# asset-tracker — Handover (v0.4.0)

**Status:** Ready for daily personal use · **Date:** 2026-07-05

## TL;DR

Local-first, stdlib-only Python CLI for tracking side projects and income. Run `asset-tracker init`, then `asset-tracker log 49.99` daily. **59/59 tests pass.** CI on Python 3.9 and 3.12.

## What ships

| Area | Status |
|---|---|
| Daily workflow (`init`, `log`, `time`, `summary`, `recent`, `doctor`) | ✅ |
| Reporting (`report`, period comparisons, rollup export) | ✅ |
| Config defaults + `last_sync` timestamps (`data/.asset-tracker.json`) | ✅ |
| Channel resolution by name/platform | ✅ |
| Live import: Stripe, Gumroad, GitHub Sponsors, Etsy | ✅ |
| `import sync` — all configured platforms at once | ✅ |
| `import csv` — Bandcamp exports + generic CSV round-trip | ✅ |
| Bandcamp live API | No (use `import csv` or manual `log`) |
| Metrics, dashboard, backup, CSV/JSON export | ✅ |
| Doctor integration health + stale-sync warnings | ✅ |
| Tests + CI | ✅ 59 tests |

## Verification

```bash
pip install -e .
PYTHONPATH=src python3 tests/test_basics.py
PYTHONPATH=src python3 tests/test_edges.py
PYTHONPATH=src python3 tests/test_daily.py
PYTHONPATH=src python3 tests/test_integrations.py
PYTHONPATH=src python3 tests/test_reporting.py

asset-tracker init --project-id demo --project-name Demo --category software --yes
asset-tracker log 25
asset-tracker report --period month
asset-tracker export-csv rollup 2026-income.csv --year 2026
asset-tracker import csv sales.csv --platform bandcamp --project demo
asset-tracker import sync --since 30d   # requires AT_LIVE_INTEGRATIONS=1 + API keys
asset-tracker doctor
```

## Known limitations

- Multi-currency conversion not implemented; metrics group by native currency (`by_currency` in JSON, per-currency rows in dashboard when mixed)
- Tax categorization not in scope (rollup export provides monthly totals for spreadsheet prep)
- Dashboard is one-shot TUI (no curses interactivity)
- Bandcamp has no public sales API — export CSV from dashboard and use `import csv`

## Sign-off

Wave 3 reporting complete. Safe to merge and use for weekly/monthly review with real data.
