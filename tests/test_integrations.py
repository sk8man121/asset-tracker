"""
test_integrations.py — Stripe live fetch (mocked) and import pipeline.

Execute: PYTHONPATH=src python3 tests/test_integrations.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import traceback
from pathlib import Path
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))

from asset_tracker import db, integrations, models, repository


PASSED = 0
FAILED = 0


def _record(name, fn):
    global PASSED, FAILED
    try:
        fn()
        PASSED += 1
        print(f"  PASS  {name}")
    except Exception:
        FAILED += 1
        print(f"  FAIL  {name}")
        traceback.print_exc()


def test_stripe_normalize():
    raw = {
        "id": "ch_abc", "amount": 2000, "amount_refunded": 0,
        "currency": "usd", "created": 1717000000,
        "metadata": {"project_id": "p1", "channel_name": "Stripe"},
    }
    conn = integrations.StripeConnector()
    nt = conn.normalize(raw)
    assert nt.external_id == "ch_abc"
    assert nt.gross_amount == 20.0
    assert nt.project_id == "p1"


def test_stripe_fetch_mocked():
    fixture = json.loads((Path(HERE) / "fixtures" / "stripe_charges.json").read_text())
    pages = [{"data": fixture, "has_more": False}]

    def fake_get_json(url, *, headers=None, params=None, timeout=30):
        assert "charges" in url
        return pages[0]

    os.environ["AT_STRIPE_API_KEY"] = "sk_test_fake"
    os.environ["AT_LIVE_INTEGRATIONS"] = "1"
    try:
        with patch("asset_tracker.http.get_json", side_effect=fake_get_json):
            conn = integrations.StripeConnector()
            txns = conn.fetch_recent("2024-01-01T00:00:00+00:00", "2026-12-31T23:59:59+00:00")
        assert len(txns) == 2
        assert txns[0].gross_amount == 50.0
        assert txns[1].kind == "recurring"
    finally:
        os.environ.pop("AT_STRIPE_API_KEY", None)
        os.environ.pop("AT_LIVE_INTEGRATIONS", None)


def test_import_live_creates_stripe_channel():
    td = tempfile.TemporaryDirectory()
    os.environ["AT_DB_PATH"] = str(Path(td.name) / "test.db")
    os.environ["AT_STRIPE_API_KEY"] = "sk_test_fake"
    os.environ["AT_LIVE_INTEGRATIONS"] = "1"
    fixture = json.loads((Path(HERE) / "fixtures" / "stripe_charges.json").read_text())
    try:
        conn = db.connect()
        db.init_schema(conn)
        repository.create_project(conn, models.Project(
            id="my-saas", name="My SaaS", category="software", status="active",
        ))
        with patch("asset_tracker.http.get_json", return_value={"data": fixture, "has_more": False}):
            ins, skp = integrations.import_live(
                conn, "stripe",
                "2024-01-01T00:00:00+00:00", "2026-12-31T23:59:59+00:00",
            )
        assert ins == 2 and skp == 0
        chs = repository.list_channels(conn, project_id="my-saas")
        assert any(c.platform == "stripe" for c in chs)
        conn.close()
    finally:
        td.cleanup()
        os.environ.pop("AT_DB_PATH", None)
        os.environ.pop("AT_STRIPE_API_KEY", None)
        os.environ.pop("AT_LIVE_INTEGRATIONS", None)


if __name__ == "__main__":
    print("=== test_integrations.py ===")
    _record("stripe normalize", test_stripe_normalize)
    _record("stripe fetch mocked", test_stripe_fetch_mocked)
    _record("import live creates stripe channel", test_import_live_creates_stripe_channel)
    print(f"\n=== {PASSED} passed, {FAILED} failed ===")
    sys.exit(1 if FAILED else 0)
