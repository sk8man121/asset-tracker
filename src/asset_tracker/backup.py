"""
backup.py — Sprint 7: persistence hardening.

Three operations:
  - snapshot(conn, keep): copy data/*.db → data/backups/<timestamp>.db (rotation)
  - export_json(conn): full data → pretty-printed JSON (one file, no FK ordering)
  - load_seed(conn, path): idempotent load from JSON seed (skips already-loaded projects)

Backups use sqlite3's own `.backup()` API which is crash-safe (handles WAL pages).
Rotation deletes oldest files when count exceeds `keep`.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import db, models, repository


def snapshot(conn: sqlite3.Connection, keep: int = 7) -> Path:
    """Copy the database to data/backups/<timestamp>.db. Rotate to keep N most recent.

    Uses the connection's actual database file path, so tests + custom db_path work.
    """
    return db.snapshot_to(conn, keep=keep)


def export_json(conn: sqlite3.Connection) -> str:
    """Serialize all data tables to JSON. Pretty-printed, ordered by id ASC."""
    payload: dict[str, list] = {}
    for table in db.list_tables(conn):
        if table == "schema_meta" or table == "sqlite_sequence":
            continue
        rows = conn.execute(f"SELECT * FROM {table} ORDER BY id ASC").fetchall()
        payload[table] = [dict(r) for r in rows]
    return json.dumps(payload, indent=2, default=str)


def load_seed(conn: sqlite3.Connection, path: Path) -> int:
    """Idempotent load from a JSON seed file. Returns count of entities created (skips existing).

    Schema (top-level keys, all optional):
      projects: [{id, name, category, status, ...}]
      income_channels: [{project_id, name, platform, kind, ...}]
      transactions: [{project_id, channel_idx, ...}]   # channel_idx references income_channels array index in the same file
      time_logs: [{project_id, minutes, started_at, ended_at}]
    """
    raw = Path(path).read_text()
    data = json.loads(raw)
    created = 0

    # 1) projects
    for p in data.get("projects", []):
        if repository.get_project(conn, p["id"]):
            continue
        # Convert ISO strings; ignore extras
        proj = models.Project(
            id=p["id"], name=p["name"], category=p["category"], status=p["status"],
            description=p.get("description"), tech_stack=p.get("tech_stack"),
            started_at=p.get("started_at"), created_at=p.get("created_at") or datetime.now(timezone.utc).isoformat(timespec="seconds"),
            notes=p.get("notes"),
        )
        repository.create_project(conn, proj)
        created += 1

    # 2) channels
    channel_ids_by_index: list[int] = []
    for i, c in enumerate(data.get("income_channels", [])):
        # Check if there's already a channel with same (project, name)
        existing = [ch for ch in repository.list_channels(conn, project_id=c["project_id"])
                    if ch.name == c["name"]]
        if existing:
            channel_ids_by_index.append(existing[0].id)
            continue
        ch = models.IncomeChannel(
            id=None,
            project_id=c["project_id"], name=c["name"], platform=c["platform"],
            kind=c["kind"], currency=c.get("currency", "USD"),
            fee_pct=c.get("fee_pct", 0.0), fee_flat=c.get("fee_flat", 0.0),
            active=c.get("active", 1),
        )
        cid = repository.create_channel(conn, ch)
        channel_ids_by_index.append(cid)
        created += 1

    # 3) transactions (channel_idx references the income_channels array above)
    for tx in data.get("transactions", []):
        idx = tx.get("channel_idx")
        if idx is None or idx >= len(channel_ids_by_index):
            continue
        cid = channel_ids_by_index[idx]
        # Idempotency check: skip if (channel_id, occurred_at, gross_amount) already present
        existing_count = conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE channel_id=? AND occurred_at=? AND gross_amount=?",
            (cid, tx["occurred_at"], tx["gross_amount"]),
        ).fetchone()[0]
        if existing_count > 0:
            continue
        ch = repository.get_channel(conn, cid)
        if not ch:
            continue
        t = models.Transaction(
            id=None,
            project_id=tx["project_id"], channel_id=cid,
            occurred_at=tx["occurred_at"], gross_amount=tx["gross_amount"],
            currency=ch.currency, net_amount=tx["gross_amount"], kind=tx["kind"],
            external_id=tx.get("external_id"), notes=tx.get("notes"),
        )
        if repository.create_transaction(conn, t) != 0:
            created += 1

    # 4) time logs
    for tl in data.get("time_logs", []):
        existing_count = conn.execute(
            "SELECT COUNT(*) FROM time_logs WHERE project_id=? AND started_at=? AND minutes=?",
            (tl["project_id"], tl["started_at"], tl["minutes"]),
        ).fetchone()[0]
        if existing_count > 0:
            continue
        repository.create_time_log(conn, models.TimeLog(
            id=None,
            project_id=tl["project_id"], started_at=tl["started_at"],
            ended_at=tl["ended_at"], minutes=tl["minutes"], notes=tl.get("notes"),
        ))
        created += 1

    return created
