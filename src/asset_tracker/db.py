"""
db.py — SQLite connection, schema bootstrap, and migration scaffolding.

Single source of truth for the asset-tracker database.
- Schema loaded from schema/schema.sql on first connection.
- Foreign keys + WAL enabled per connection.
- Idempotent: safe to call init() repeatedly.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Iterable, Optional


# Resolve schema.sql relative to the repo root, not the package.
REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "schema" / "schema.sql"


def default_db_path() -> Path:
    """Return the default DB path. Honors AT_DB_PATH env, else ./data/asset-tracker.db."""
    env = os.environ.get("AT_DB_PATH")
    if env:
        return Path(env).expanduser().resolve()
    return REPO_ROOT / "data" / "asset-tracker.db"


def connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Open a connection with FK + WAL enabled. Caller closes."""
    path = Path(db_path) if db_path else default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_schema(conn: sqlite3.Connection, schema_path: Path = SCHEMA_PATH) -> None:
    """Execute schema.sql on a connection. Idempotent."""
    sql = schema_path.read_text()
    conn.executescript(sql)
    conn.commit()


def get_schema_version(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()
    return row["value"] if row else "0"


def list_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    return [r["name"] for r in rows]


def integrity_check(conn: sqlite3.Connection) -> str:
    """Returns 'ok' if SQLite's own integrity_check passes, else the violation string."""
    row = conn.execute("PRAGMA integrity_check").fetchone()
    return row[0] if row else "unknown"


def table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Return {table_name: row_count} for all data tables. Skips schema_meta."""
    counts = {}
    skip = {"schema_meta"}
    for t in list_tables(conn):
        if t in skip:
            continue
        counts[t] = conn.execute(f"SELECT COUNT(*) AS c FROM {t}").fetchone()["c"]
    return counts
