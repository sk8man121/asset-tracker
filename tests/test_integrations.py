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

from asset_tracker import db, integrations, models, repository, csv_import, config, onboard
from asset_tracker import csv_export


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


def test_gumroad_fetch_mocked():
    fixture = json.loads((Path(HERE) / "fixtures" / "gumroad_sales.json").read_text())

    def fake_get_json(url, *, headers=None, params=None, timeout=30):
        if "sales" in url:
            return {"success": True, "sales": fixture, "next_page_url": None}
        return {"success": True, "user": {"email": "test@gumroad.com"}}

    os.environ["AT_GUMROAD_ACCESS_TOKEN"] = "tok_fake"
    os.environ["AT_LIVE_INTEGRATIONS"] = "1"
    try:
        with patch("asset_tracker.http.get_json", side_effect=fake_get_json):
            conn = integrations.GumroadConnector()
            txns = conn.fetch_recent("2026-01-01T00:00:00+00:00", "2026-12-31T23:59:59+00:00")
        assert len(txns) == 1
        assert txns[0].gross_amount == 25.0
        assert txns[0].kind == "recurring"
    finally:
        os.environ.pop("AT_GUMROAD_ACCESS_TOKEN", None)
        os.environ.pop("AT_LIVE_INTEGRATIONS", None)


def test_github_fetch_mocked():
    fixture = json.loads((Path(HERE) / "fixtures" / "github_sponsors.json").read_text())

    def fake_post_json(url, *, headers=None, body=None, timeout=30):
        return fixture

    os.environ["AT_GITHUB_TOKEN"] = "ghp_fake"
    os.environ["AT_LIVE_INTEGRATIONS"] = "1"
    try:
        with patch("asset_tracker.http.post_json", side_effect=fake_post_json):
            conn = integrations.GitHubSponsorsConnector()
            txns = conn.fetch_recent("2026-01-01T00:00:00+00:00", "2026-12-31T23:59:59+00:00")
        assert len(txns) == 1
        assert txns[0].gross_amount == 25.0
        assert txns[0].kind == "recurring"
    finally:
        os.environ.pop("AT_GITHUB_TOKEN", None)
        os.environ.pop("AT_LIVE_INTEGRATIONS", None)


def test_etsy_fetch_mocked():
    fixture = json.loads((Path(HERE) / "fixtures" / "etsy_receipts.json").read_text())

    def fake_get_json(url, *, headers=None, params=None, timeout=30):
        if "receipts" in url:
            return fixture
        return {"shop_name": "Test Shop"}

    os.environ["AT_ETSY_API_KEY"] = "etsy_fake"
    os.environ["AT_ETSY_SHOP_ID"] = "12345"
    os.environ["AT_LIVE_INTEGRATIONS"] = "1"
    try:
        with patch("asset_tracker.http.get_json", side_effect=fake_get_json):
            conn = integrations.EtsyConnector()
            txns = conn.fetch_recent("2024-01-01T00:00:00+00:00", "2026-12-31T23:59:59+00:00")
        assert len(txns) == 1
        assert txns[0].gross_amount == 42.50
        assert txns[0].net_amount == 38.25
    finally:
        os.environ.pop("AT_ETSY_API_KEY", None)
        os.environ.pop("AT_ETSY_SHOP_ID", None)
        os.environ.pop("AT_LIVE_INTEGRATIONS", None)


def test_import_project_override():
    td = tempfile.TemporaryDirectory()
    os.environ["AT_DB_PATH"] = str(Path(td.name) / "test.db")
    os.environ["AT_STRIPE_API_KEY"] = "sk_test_fake"
    os.environ["AT_LIVE_INTEGRATIONS"] = "1"
    fixture = json.loads((Path(HERE) / "fixtures" / "stripe_charges.json").read_text())
    try:
        conn = db.connect()
        db.init_schema(conn)
        repository.create_project(conn, models.Project(
            id="target-proj", name="Target", category="software", status="active",
        ))
        resolver = {"__force__": "target-proj"}
        with patch("asset_tracker.http.get_json", return_value={"data": fixture, "has_more": False}):
            ins, _ = integrations.import_live(
                conn, "stripe",
                "2024-01-01T00:00:00+00:00", "2026-12-31T23:59:59+00:00",
                project_resolver=resolver,
            )
        assert ins == 2
        txs = repository.list_transactions(conn, project_id="target-proj")
        assert len(txs) == 2
        conn.close()
    finally:
        td.cleanup()
        os.environ.pop("AT_DB_PATH", None)
        os.environ.pop("AT_STRIPE_API_KEY", None)
        os.environ.pop("AT_LIVE_INTEGRATIONS", None)


def test_import_config_project_map():
    td = tempfile.TemporaryDirectory()
    db_path = Path(td.name) / "test.db"
    os.environ["AT_DB_PATH"] = str(db_path)
    os.environ["AT_STRIPE_API_KEY"] = "sk_test_fake"
    os.environ["AT_LIVE_INTEGRATIONS"] = "1"
    fixture = [{
        "id": "ch_unassigned",
        "amount": 1000,
        "amount_refunded": 0,
        "currency": "usd",
        "created": 1717000000,
        "metadata": {},
        "invoice": None
    }]
    try:
        cfg_path = db_path.parent / ".asset-tracker.json"
        cfg_path.write_text(json.dumps({"import_project_map": {"unassigned": "mapped-proj"}}))
        conn = db.connect()
        db.init_schema(conn)
        repository.create_project(conn, models.Project(
            id="mapped-proj", name="Mapped", category="software", status="active",
        ))
        with patch("asset_tracker.http.get_json", return_value={"data": fixture, "has_more": False}):
            ins, _ = integrations.import_live(
                conn, "stripe",
                "2024-01-01T00:00:00+00:00", "2026-12-31T23:59:59+00:00",
                project_resolver={"unassigned": "mapped-proj"},
            )
        assert ins == 1
        txs = repository.list_transactions(conn, project_id="mapped-proj")
        assert len(txs) == 1
        conn.close()
    finally:
        td.cleanup()
        os.environ.pop("AT_DB_PATH", None)
        os.environ.pop("AT_STRIPE_API_KEY", None)
        os.environ.pop("AT_LIVE_INTEGRATIONS", None)


def test_csv_import_bandcamp_fixture():
    fixture = Path(HERE) / "fixtures" / "bandcamp_sales.csv"
    txns, rejected = csv_import.parse_csv_rows(fixture, platform="bandcamp")
    assert rejected == 0
    assert len(txns) == 3
    assert txns[0].gross_amount == 7.0
    assert txns[0].external_id == "pp_tx_001"
    assert txns[2].currency == "EUR"


def test_csv_import_idempotent():
    td = tempfile.TemporaryDirectory()
    os.environ["AT_DB_PATH"] = str(Path(td.name) / "test.db")
    fixture = Path(HERE) / "fixtures" / "bandcamp_sales.csv"
    try:
        conn = db.connect()
        db.init_schema(conn)
        repository.create_project(conn, models.Project(
            id="my-album", name="My Album", category="music", status="active",
        ))
        resolver = {"__force__": "my-album"}
        ins1, skp1, _ = csv_import.import_csv(
            conn, fixture, platform="bandcamp", project_resolver=resolver,
        )
        ins2, skp2, _ = csv_import.import_csv(
            conn, fixture, platform="bandcamp", project_resolver=resolver,
        )
        assert ins1 == 3 and skp1 == 0
        assert ins2 == 0 and skp2 == 3
        assert config.get_last_sync().get("csv:bandcamp")
        conn.close()
    finally:
        td.cleanup()
        os.environ.pop("AT_DB_PATH", None)


def test_csv_import_generic_roundtrip():
    td = tempfile.TemporaryDirectory()
    os.environ["AT_DB_PATH"] = str(Path(td.name) / "test.db")
    csv_path = Path(td.name) / "roundtrip.csv"
    try:
        conn = db.connect()
        db.init_schema(conn)
        repository.create_project(conn, models.Project(
            id="rt-proj", name="RT", category="software", status="active",
        ))
        repository.create_channel(conn, models.IncomeChannel(
            id=None, project_id="rt-proj", name="Test", platform="direct", kind="one_time",
        ))
        ch_id = repository.list_channels(conn, project_id="rt-proj")[0].id
        repository.create_transaction(conn, models.Transaction(
            id=None, project_id="rt-proj", channel_id=ch_id,
            occurred_at="2026-06-01T12:00:00+00:00",
            gross_amount=100.0, currency="USD", net_amount=90.0,
            kind="one_time", fee_amount=10.0, external_id="rt_001",
        ))
        n = csv_export.export_transactions_csv(conn, csv_path, project_id="rt-proj")
        assert n == 1
        conn.execute("DELETE FROM transactions")
        ins, skp, rejected = csv_import.import_csv(
            conn, csv_path, platform="generic",
            project_resolver={"__force__": "rt-proj"},
        )
        assert rejected == 0
        assert ins == 1 and skp == 0
        txs = repository.list_transactions(conn, project_id="rt-proj")
        assert len(txs) == 1
        conn.close()
    finally:
        td.cleanup()
        os.environ.pop("AT_DB_PATH", None)


def test_import_sync_skips_unconfigured():
    td = tempfile.TemporaryDirectory()
    os.environ["AT_DB_PATH"] = str(Path(td.name) / "test.db")
    os.environ["AT_LIVE_INTEGRATIONS"] = "1"
    try:
        conn = db.connect()
        db.init_schema(conn)
        results = integrations.import_sync(
            conn, "2024-01-01T00:00:00+00:00", "2026-12-31T23:59:59+00:00",
        )
        assert results == {}
        conn.close()
    finally:
        td.cleanup()
        os.environ.pop("AT_DB_PATH", None)
        os.environ.pop("AT_LIVE_INTEGRATIONS", None)


def test_import_sync_mocked():
    td = tempfile.TemporaryDirectory()
    os.environ["AT_DB_PATH"] = str(Path(td.name) / "test.db")
    os.environ["AT_STRIPE_API_KEY"] = "sk_test_fake"
    os.environ["AT_GUMROAD_ACCESS_TOKEN"] = "tok_fake"
    os.environ["AT_BANDCAMP_FAN_TOKEN"] = "bc_fake"
    os.environ["AT_LIVE_INTEGRATIONS"] = "1"
    stripe_fixture = json.loads((Path(HERE) / "fixtures" / "stripe_charges.json").read_text())
    gumroad_fixture = json.loads((Path(HERE) / "fixtures" / "gumroad_sales.json").read_text())

    def fake_get_json(url, *, headers=None, params=None, timeout=30):
        if "charges" in url:
            return {"data": stripe_fixture, "has_more": False}
        if "sales" in url:
            return {"success": True, "sales": gumroad_fixture, "next_page_url": None}
        return {}

    try:
        conn = db.connect()
        db.init_schema(conn)
        with patch("asset_tracker.http.get_json", side_effect=fake_get_json):
            results = integrations.import_sync(
                conn, "2024-01-01T00:00:00+00:00", "2026-12-31T23:59:59+00:00",
            )
        assert results["stripe"] == (2, 0)
        assert results["gumroad"] == (1, 0)
        assert results["bandcamp"] == "skipped: no live API (use import csv)"
        assert "stripe" in config.get_last_sync()
        conn.close()
    finally:
        td.cleanup()
        os.environ.pop("AT_DB_PATH", None)
        os.environ.pop("AT_STRIPE_API_KEY", None)
        os.environ.pop("AT_GUMROAD_ACCESS_TOKEN", None)
        os.environ.pop("AT_BANDCAMP_FAN_TOKEN", None)
        os.environ.pop("AT_LIVE_INTEGRATIONS", None)


def test_doctor_shows_integrations():
    td = tempfile.TemporaryDirectory()
    os.environ["AT_DB_PATH"] = str(Path(td.name) / "test.db")
    os.environ["AT_STRIPE_API_KEY"] = "sk_test_fake"
    try:
        conn = db.connect()
        db.init_schema(conn)
        out = onboard.run_doctor(conn)
        assert "integrations:" in out
        assert "stripe" in out
        conn.close()
    finally:
        td.cleanup()
        os.environ.pop("AT_DB_PATH", None)
        os.environ.pop("AT_STRIPE_API_KEY", None)


if __name__ == "__main__":
    print("=== test_integrations.py ===")
    _record("stripe normalize", test_stripe_normalize)
    _record("stripe fetch mocked", test_stripe_fetch_mocked)
    _record("import live creates stripe channel", test_import_live_creates_stripe_channel)
    _record("gumroad fetch mocked", test_gumroad_fetch_mocked)
    _record("github sponsors fetch mocked", test_github_fetch_mocked)
    _record("etsy fetch mocked", test_etsy_fetch_mocked)
    _record("import project override", test_import_project_override)
    _record("import config project map", test_import_config_project_map)
    _record("csv import bandcamp fixture", test_csv_import_bandcamp_fixture)
    _record("csv import idempotent", test_csv_import_idempotent)
    _record("csv import generic roundtrip", test_csv_import_generic_roundtrip)
    _record("import sync skips unconfigured", test_import_sync_skips_unconfigured)
    _record("import sync mocked", test_import_sync_mocked)
    _record("doctor shows integrations", test_doctor_shows_integrations)
    print(f"\n=== {PASSED} passed, {FAILED} failed ===")
    sys.exit(1 if FAILED else 0)
