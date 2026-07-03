"""
test_daily.py — Daily-use workflow: init, config, quick log, channel resolution, time.

Execute: PYTHONPATH=src python3 tests/test_daily.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import traceback
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))

from asset_tracker import cli, config, db, models, onboard, repository


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


def _fresh_env():
    td = tempfile.TemporaryDirectory()
    db_path = Path(td.name) / "test.db"
    cfg_path = db_path.parent / ".asset-tracker.json"
    os.environ["AT_DB_PATH"] = str(db_path)
    conn = db.connect()
    db.init_schema(conn)
    return td, conn, db_path, cfg_path


def test_config_roundtrip():
    td, conn, db_path, cfg_path = _fresh_env()
    try:
        config.set_defaults(default_project="my-app", default_channel="stripe")
        assert cfg_path.exists()
        data = json.loads(cfg_path.read_text())
        assert data["default_project"] == "my-app"
        assert data["default_channel"] == "stripe"
        assert config.get_default("default_project") == "my-app"
    finally:
        conn.close()
        td.cleanup()
        os.environ.pop("AT_DB_PATH", None)


def test_resolve_channel_by_name_and_platform():
    td, conn, _, _ = _fresh_env()
    try:
        repository.create_project(conn, models.Project(
            id="p1", name="P1", category="software", status="active",
        ))
        cid = repository.create_channel(conn, models.IncomeChannel(
            id=None, project_id="p1", name="Gumroad MRR",
            platform="gumroad", kind="recurring", fee_pct=0.10,
        ))
        ch = repository.resolve_channel(conn, "p1", "Gumroad MRR")
        assert ch.id == cid
        ch2 = repository.resolve_channel(conn, "p1", "gumroad")
        assert ch2.id == cid
        ch3 = repository.resolve_channel(conn, "p1", str(cid))
        assert ch3.id == cid
    finally:
        conn.close()
        td.cleanup()
        os.environ.pop("AT_DB_PATH", None)


def test_init_noninteractive():
    td, conn, _, cfg_path = _fresh_env()
    try:
        msg = onboard.run_init(
            conn, interactive=False,
            project_id="saas", project_name="My SaaS", category="software",
        )
        assert "initialized" in msg
        assert onboard.is_initialized(conn)
        assert cfg_path.exists()
        assert config.get_default("default_project") == "saas"
    finally:
        conn.close()
        td.cleanup()
        os.environ.pop("AT_DB_PATH", None)


def test_quick_log_with_defaults():
    td, conn, _, _ = _fresh_env()
    try:
        onboard.run_init(conn, interactive=False, project_id="app", project_name="App", category="software")
        cli.main(["log", "100", "--notes", "test sale"])
        txs = repository.list_transactions(conn)
        assert len(txs) == 1
        assert txs[0].gross_amount == 100.0
        assert txs[0].net_amount == 100.0  # direct channel, no fee
    finally:
        conn.close()
        td.cleanup()
        os.environ.pop("AT_DB_PATH", None)


def test_quick_log_auto_fee():
    td, conn, _, _ = _fresh_env()
    try:
        repository.create_project(conn, models.Project(
            id="p", name="P", category="software", status="active",
        ))
        repository.create_channel(conn, models.IncomeChannel(
            id=None, project_id="p", name="Gumroad", platform="gumroad",
            kind="recurring", fee_pct=0.10,
        ))
        config.set_defaults(default_project="p", default_channel="Gumroad")
        cli.main(["log", "100"])
        txs = repository.list_transactions(conn)
        assert len(txs) == 1
        assert txs[0].fee_amount == 10.0
        assert txs[0].net_amount == 90.0
    finally:
        conn.close()
        td.cleanup()
        os.environ.pop("AT_DB_PATH", None)


def test_time_log():
    td, conn, _, _ = _fresh_env()
    try:
        onboard.run_init(conn, interactive=False, project_id="app", project_name="App", category="software")
        cli.main(["time", "log", "--minutes", "90", "--notes", "coding"])
        logs = repository.list_time_logs(conn)
        assert len(logs) == 1
        assert logs[0].minutes == 90
        assert logs[0].notes == "coding"
    finally:
        conn.close()
        td.cleanup()
        os.environ.pop("AT_DB_PATH", None)


def test_doctor_empty():
    td, conn, _, _ = _fresh_env()
    try:
        report = onboard.run_doctor(conn)
        assert "database is empty" in report or "run `asset-tracker init`" in report
        assert "integrity: ok" in report
    finally:
        conn.close()
        td.cleanup()
        os.environ.pop("AT_DB_PATH", None)


def test_doctor_healthy():
    td, conn, _, _ = _fresh_env()
    try:
        onboard.run_init(conn, interactive=False, project_id="app", project_name="App", category="software")
        cli.main(["log", "50"])
        report = onboard.run_doctor(conn)
        assert "status: healthy" in report
        assert "transactions: 1" in report
    finally:
        conn.close()
        td.cleanup()
        os.environ.pop("AT_DB_PATH", None)


def test_dashboard_empty_hint():
    td, conn, _, _ = _fresh_env()
    try:
        from asset_tracker import dashboard
        out = dashboard.render(conn)
        assert "Getting started" in out
        assert "asset-tracker init" in out
    finally:
        conn.close()
        td.cleanup()
        os.environ.pop("AT_DB_PATH", None)


if __name__ == "__main__":
    print("=== test_daily.py ===")
    _record("config roundtrip", test_config_roundtrip)
    _record("resolve channel by name/platform/id", test_resolve_channel_by_name_and_platform)
    _record("init noninteractive", test_init_noninteractive)
    _record("quick log with defaults", test_quick_log_with_defaults)
    _record("quick log auto fee", test_quick_log_auto_fee)
    _record("time log", test_time_log)
    _record("doctor empty", test_doctor_empty)
    _record("doctor healthy", test_doctor_healthy)
    _record("dashboard empty hint", test_dashboard_empty_hint)
    print(f"\n=== {PASSED} passed, {FAILED} failed ===")
    sys.exit(1 if FAILED else 0)
