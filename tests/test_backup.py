"""
test_backup.py — Wave 4: snapshot rotation, JSON export, seed load.

Execute: PYTHONPATH=src python3 tests/test_backup.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))

from asset_tracker import backup, db, models, repository


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
    os.environ["AT_DB_PATH"] = str(db_path)
    conn = db.connect()
    db.init_schema(conn)
    return td, conn, db_path


def test_snapshot_creates_file():
    td, conn, db_path = _fresh_env()
    try:
        dest = backup.snapshot(conn, keep=7)
        assert dest.exists()
        assert dest.suffix == ".db"
        assert dest.parent.name == "backups"
        assert dest.parent == db_path.parent / "backups"
    finally:
        conn.close()
        td.cleanup()
        os.environ.pop("AT_DB_PATH", None)


def test_snapshot_rotation_respects_keep():
    td, conn, _db_path = _fresh_env()
    try:
        paths = []
        for _ in range(4):
            paths.append(backup.snapshot(conn, keep=2))
            time.sleep(1.05)  # distinct second-resolution timestamps
        backups_dir = paths[-1].parent
        remaining = sorted(backups_dir.glob("asset-tracker-*.db"))
        assert len(remaining) == 2, f"expected 2 backups, got {len(remaining)}: {remaining}"
        # Newest two should remain
        assert paths[-1] in remaining or paths[-1].exists()
        assert paths[-2].exists()
        assert not paths[0].exists()
        assert not paths[1].exists()
    finally:
        conn.close()
        td.cleanup()
        os.environ.pop("AT_DB_PATH", None)


def test_export_json_roundtrip_keys():
    td, conn, _db_path = _fresh_env()
    try:
        repository.create_project(conn, models.Project(
            id="p1", name="Proj", category="software", status="active",
        ))
        cid = repository.create_channel(conn, models.IncomeChannel(
            id=None, project_id="p1", name="Direct", platform="direct",
            kind="one_time", currency="USD",
        ))
        repository.create_transaction(conn, models.Transaction(
            id=None, project_id="p1", channel_id=cid,
            occurred_at="2026-01-01T00:00:00+00:00",
            gross_amount=10, net_amount=10, currency="USD", kind="one_time",
        ))
        payload = json.loads(backup.export_json(conn))
        assert "projects" in payload
        assert "income_channels" in payload
        assert "transactions" in payload
        assert "time_logs" in payload
        assert "schema_meta" not in payload
        assert len(payload["projects"]) == 1
        assert payload["projects"][0]["id"] == "p1"
        assert len(payload["transactions"]) == 1
    finally:
        conn.close()
        td.cleanup()
        os.environ.pop("AT_DB_PATH", None)


def test_load_seed_idempotent():
    td, conn, _db_path = _fresh_env()
    seed_path = Path(HERE) / ".." / "seed" / "seed.json"
    try:
        created1 = backup.load_seed(conn, seed_path)
        assert created1 > 0
        counts1 = db.table_counts(conn)
        created2 = backup.load_seed(conn, seed_path)
        assert created2 == 0
        counts2 = db.table_counts(conn)
        assert counts1 == counts2
        assert counts1.get("projects", 0) >= 1
    finally:
        conn.close()
        td.cleanup()
        os.environ.pop("AT_DB_PATH", None)


def main():
    print("=== test_backup.py ===")
    _record("snapshot creates file", test_snapshot_creates_file)
    _record("snapshot rotation respects keep", test_snapshot_rotation_respects_keep)
    _record("export_json roundtrip keys", test_export_json_roundtrip_keys)
    _record("load_seed idempotent", test_load_seed_idempotent)
    print(f"\n=== {PASSED} passed, {FAILED} failed ===")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
