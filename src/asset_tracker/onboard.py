"""
onboard.py — First-run setup wizard and health checks.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from . import config, db, models, repository
from . import integrations


def is_initialized(conn: sqlite3.Connection) -> bool:
    """True when the database has at least one project."""
    row = conn.execute("SELECT COUNT(*) AS c FROM projects").fetchone()
    return bool(row and row["c"] > 0)


def run_init(
    conn: sqlite3.Connection,
    *,
    interactive: bool = True,
    from_seed: bool = False,
    seed_path: Optional[Path] = None,
    project_id: Optional[str] = None,
    project_name: Optional[str] = None,
    category: str = "software",
) -> str:
    """Initialize a fresh database. Returns a human-readable status message."""
    if is_initialized(conn):
        counts = db.table_counts(conn)
        return (
            f"already initialized — {counts.get('projects', 0)} projects, "
            f"{counts.get('transactions', 0)} transactions. "
            f"Run `asset-tracker doctor` to check health."
        )

    if from_seed:
        from . import backup as backup_mod
        path = seed_path or (db.REPO_ROOT / "seed" / "seed.json")
        if not path.exists():
            raise FileNotFoundError(f"seed file not found: {path}")
        count = backup_mod.load_seed(conn, path)
        first = conn.execute("SELECT id FROM projects ORDER BY created_at LIMIT 1").fetchone()
        if first:
            config.set_defaults(default_project=first["id"])
        return f"initialized from seed ({count} entities). Default project: {first['id'] if first else '—'}"

    if not interactive:
        if not project_id or not project_name:
            raise ValueError("non-interactive init requires --project-id and --project-name")
        return _create_first_project(conn, project_id, project_name, category, interactive=False)

    print("Welcome to asset-tracker — let's set up your first project.\n")
    project_id = _prompt("Project id (slug, e.g. my-saas-app)", project_id)
    project_name = _prompt("Display name", project_name or project_id.replace("-", " ").title())
    category = _prompt_category(category)
    return _create_first_project(conn, project_id, project_name, category, interactive=True)


def _create_first_project(
    conn: sqlite3.Connection,
    project_id: str,
    project_name: str,
    category: str,
    *,
    interactive: bool,
) -> str:
    repository.create_project(conn, models.Project(
        id=project_id,
        name=project_name,
        category=category,
        status="active",
    ))

    channel_name: Optional[str] = None
    platform = "direct"
    kind = "one_time"
    fee_pct = 0.0

    if interactive:
        add_channel = _prompt_yes("Add your first income channel now?", default=True)
        if add_channel:
            platform = _prompt_platform("Platform", "direct")
            channel_name = _prompt("Channel name", f"{platform.title()} sales")
            kind = _prompt_kind("Income kind", "one_time")
            fee_str = _prompt("Fee percent (0 for none)", "0")
            try:
                fee_pct = float(fee_str) / 100.0
            except ValueError:
                fee_pct = 0.0
    else:
        channel_name = "Direct sales"

    channel_id = None
    if channel_name:
        channel_id = repository.create_channel(conn, models.IncomeChannel(
            id=None,
            project_id=project_id,
            name=channel_name,
            platform=platform,
            kind=kind,
            fee_pct=fee_pct,
        ))
        config.set_defaults(default_project=project_id, default_channel=channel_name)

    lines = [
        f"initialized — project '{project_id}' created",
        f"database: {db.default_db_path()}",
        f"config: {config.config_path()}",
    ]
    if channel_id:
        lines.append(f"channel: #{channel_id} '{channel_name}' ({platform}, {kind})")
    lines.append("")
    lines.append("Next steps:")
    lines.append(f"  asset-tracker log 49.99 --notes \"first sale\"")
    lines.append(f"  asset-tracker dashboard")
    return "\n".join(lines)


def run_doctor(conn: sqlite3.Connection) -> str:
    """Health check with actionable guidance."""
    lines: list[str] = []
    db_path = db.default_db_path()
    cfg_path = config.config_path()
    cfg = config.load_config()

    lines.append(f"database: {db_path}")
    lines.append(f"  exists: {'yes' if db_path.exists() else 'no'}")
    lines.append(f"  integrity: {db.integrity_check(conn)}")
    lines.append(f"  schema: v{db.get_schema_version(conn)}")

    counts = db.table_counts(conn)
    lines.append("")
    lines.append("counts:")
    for table in ("projects", "income_channels", "transactions", "time_logs"):
        lines.append(f"  {table}: {counts.get(table, 0)}")

    lines.append("")
    lines.append(f"config: {cfg_path}")
    lines.append(f"  exists: {'yes' if cfg_path.exists() else 'no'}")
    if cfg.get("default_project"):
        lines.append(f"  default_project: {cfg['default_project']}")
    if cfg.get("default_channel"):
        lines.append(f"  default_channel: {cfg['default_channel']}")

    issues: list[str] = []
    tips: list[str] = []

    lines.append("")
    lines.append("integrations:")
    live = bool(os.environ.get("AT_LIVE_INTEGRATIONS"))
    lines.append(f"  live imports: {'on' if live else 'off'}")
    last_sync = config.get_last_sync()
    now = datetime.now(timezone.utc)
    stale_threshold = now - timedelta(days=30)
    for c in integrations.REGISTRY:
        conn_obj = integrations.get_connector(c.platform_id)
        ok, msg = conn_obj.verify()
        if conn_obj.is_configured():
            marker = "●" if ok else "✗"
            sync_at = last_sync.get(c.platform_id)
            sync_note = f"last sync: {sync_at[:10]}" if sync_at else "never synced"
            lines.append(f"  {marker} {c.platform_id:16}  {msg}  ({sync_note})")
            if sync_at:
                try:
                    sync_dt = datetime.fromisoformat(sync_at.replace("Z", "+00:00"))
                    if sync_dt.tzinfo is None:
                        sync_dt = sync_dt.replace(tzinfo=timezone.utc)
                    if sync_dt < stale_threshold:
                        tips.append(
                            f"{c.platform_id} last synced {sync_at[:10]} — "
                            "run `asset-tracker import sync`"
                        )
                except ValueError:
                    pass
            elif c.platform_id != "bandcamp":
                tips.append(f"{c.platform_id} configured but never synced — run `asset-tracker import {c.platform_id}`")
        else:
            lines.append(f"  ○ {c.platform_id:16}  not configured")

    if not is_initialized(conn):
        issues.append("database is empty — run `asset-tracker init`")
    elif counts.get("transactions", 0) == 0:
        tips.append("log your first transaction: `asset-tracker log <amount>`")
    if counts.get("projects", 0) > 0 and counts.get("income_channels", 0) == 0:
        issues.append("projects exist but no income channels — add one with `channel add`")
    unassigned = repository.get_project(conn, "unassigned")
    if unassigned:
        tx_count = conn.execute(
            "SELECT COUNT(*) AS c FROM transactions WHERE project_id = ?",
            ("unassigned",),
        ).fetchone()["c"]
        if tx_count > 0:
            issues.append(
                f"project 'unassigned' has {tx_count} imported txns — "
                "set import_project_map in config or re-import with --project"
            )
    if not cfg.get("default_project") and counts.get("projects", 0) == 1:
        pid = conn.execute("SELECT id FROM projects LIMIT 1").fetchone()["id"]
        tips.append(f"set a default project: config will auto-set on next `log` (currently: {pid})")

    backup_dir = db_path.parent / "backups"
    if db_path.exists() and not any(backup_dir.glob("asset-tracker-*.db")):
        tips.append("no backups yet — run `asset-tracker backup`")

    lines.append("")
    if issues:
        lines.append("issues:")
        for i in issues:
            lines.append(f"  ✗ {i}")
    else:
        lines.append("status: healthy")
    if tips:
        lines.append("")
        lines.append("tips:")
        for t in tips:
            lines.append(f"  → {t}")

    return "\n".join(lines)


def _prompt(label: str, default: Optional[str] = None) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        val = input(f"{label}{suffix}: ").strip()
        if val:
            return val
        if default is not None:
            return default
        print("  (required)")


def _prompt_yes(label: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    val = input(f"{label} ({hint}): ").strip().lower()
    if not val:
        return default
    return val in ("y", "yes")


def _prompt_category(default: str) -> str:
    cats = sorted(models.VALID_CATEGORIES)
    print(f"Categories: {', '.join(cats)}")
    val = _prompt("Category", default)
    if val not in models.VALID_CATEGORIES:
        print(f"  using '{default}' — '{val}' is not valid")
        return default
    return val


def _prompt_platform(label: str, default: str) -> str:
    plats = sorted(models.VALID_PLATFORMS)
    print(f"Platforms: {', '.join(plats)}")
    val = _prompt(label, default)
    if val not in models.VALID_PLATFORMS:
        print(f"  using '{default}' — '{val}' is not valid")
        return default
    return val


def _prompt_kind(label: str, default: str) -> str:
    kinds = sorted(models.VALID_KINDS)
    print(f"Kinds: {', '.join(kinds)}")
    val = _prompt(label, default)
    if val not in models.VALID_KINDS:
        print(f"  using '{default}' — '{val}' is not valid")
        return default
    return val
