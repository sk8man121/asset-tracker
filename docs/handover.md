# asset-tracker — Handover (v0.2.1)

**Status:** Ready for daily personal use · **Date:** 2026-07-03

## TL;DR

Local-first, stdlib-only Python CLI for tracking side projects and income. Run `asset-tracker init`, then `asset-tracker log 49.99` daily. **38/38 tests pass.** CI on Python 3.9 and 3.12.

## What ships

| Area | Status |
|---|---|
| Daily workflow (`init`, `log`, `time`, `summary`, `recent`, `doctor`) | ✅ |
| Config defaults (`data/.asset-tracker.json`) | ✅ |
| Channel resolution by name/platform | ✅ |
| Stripe live import (`import stripe`, stdlib urllib) | ✅ |
| Gumroad/Bandcamp/GitHub/Etsy | Stub (normalize + mock import) |
| Metrics, dashboard, backup, CSV/JSON export | ✅ |
| Tests + CI | ✅ 38 tests |

## Verification

```bash
pip install -e .
PYTHONPATH=src python3 tests/test_basics.py
PYTHONPATH=src python3 tests/test_edges.py
PYTHONPATH=src python3 tests/test_daily.py
PYTHONPATH=src python3 tests/test_integrations.py

asset-tracker init --project-id demo --project-name Demo --category software --yes
asset-tracker log 25
asset-tracker doctor
```

## Known limitations

- Multi-currency conversion not implemented (store native currency per txn)
- Tax categorization not in scope
- Dashboard is one-shot TUI (no curses interactivity)
- Only Stripe has live HTTP fetch; other platforms need API wiring

## Sign-off

Productization sprint complete. Safe to merge and use with real data.
