"""
cli.py — argparse-based CLI for asset-tracker.

Usage (after install: `pip install -e .`):
    asset-tracker project add <id> --name <name> [--category software] [--status active] ...
    asset-tracker project list [--status active] [--category music]
    asset-tracker project show <id>
    asset-tracker project update <id> [--name X] [--status dormant] ...
    asset-tracker channel add --project <id> --name <n> --platform gumroad --kind recurring [--fee 10]
    asset-tracker channel list [--project <id>]
    asset-tracker tx log --project <id> --channel <id> --gross 100 --kind recurring [--external stripe_evt_X] [--date 2026-06-28]
    asset-tracker tx list [--project X] [--since 2026-01-01] [--until 2026-12-31]
    asset-tracker metrics [--project <id>] [--period 30d|90d|ytd|all]
    asset-tracker dashboard
    asset-tracker backup
    asset-tracker export [path]
    asset-tracker seed [path]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import db, models, repository
from . import metrics as metrics_mod
from . import dashboard as dashboard_mod
from . import backup as backup_mod
from . import integrations
from . import _compat
from . import csv_export


# ---------- helpers ----------

def _exit_err(msg: str, code: int = 1) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def _ok(msg: str) -> None:
    print(msg)


def _parse_date(s: str | None) -> str | None:
    """Parse a date string. Accepts YYYY-MM-DD or full ISO. Returns ISO."""
    if not s:
        return None
    if "T" in s:
        return s
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc).isoformat(timespec="seconds")


# ---------- subcommand builders ----------

def cmd_project_add(args, conn):
    p = models.Project(
        id=args.id,
        name=args.name,
        category=args.category,
        status=args.status,
        description=args.description,
        tech_stack=args.tech_stack,
        repo_url=args.repo_url,
        repo_local_path=args.repo_local_path,
    )
    repository.create_project(conn, p)
    _ok(f"project '{p.id}' created")


def cmd_project_list(args, conn):
    projs = repository.list_projects(conn, status=args.status, category=args.category)
    if not projs:
        _ok("no projects")
        return
    for p in projs:
        print(f"  {p.id:30}  [{p.category:8}]  [{p.status:8}]  {p.name}")


def cmd_project_show(args, conn):
    p = repository.get_project(conn, args.id)
    if not p:
        _exit_err(f"project not found: {args.id}")
    print(json.dumps(p.to_dict(), indent=2))


def cmd_project_update(args, conn):
    fields = {}
    for k in ("name", "category", "status", "description", "tech_stack",
              "repo_url", "repo_local_path"):
        v = getattr(args, k, None)
        if v is not None:
            fields[k] = v
    if not fields:
        _exit_err("no fields to update")
    repository.update_project(conn, args.id, fields)
    _ok(f"project '{args.id}' updated")


def cmd_channel_add(args, conn):
    if not repository.get_project(conn, args.project):
        _exit_err(f"project not found: {args.project}")
    c = models.IncomeChannel(
        id=None,
        project_id=args.project,
        name=args.name,
        platform=args.platform,
        kind=args.kind,
        currency=args.currency,
        fee_pct=(args.fee or 0) / 100.0,
        fee_flat=(args.flat or 0),
        active=1 if args.active else 0,
    )
    cid = repository.create_channel(conn, c)
    _ok(f"channel #{cid} created for project '{args.project}'")


def cmd_channel_list(args, conn):
    chs = repository.list_channels(conn, project_id=args.project)
    if not chs:
        _ok("no channels")
        return
    for c in chs:
        active = "●" if c.active else "○"
        fee_str = ""
        if c.fee_pct:
            fee_str += f"{c.fee_pct*100:.1f}%"
        if c.fee_flat:
            fee_str += f"+{c.fee_flat:.2f}"
        print(f"  {active} #{c.id:>3}  {c.project_id:30}  {c.platform:14}  [{c.kind:9}]  {c.name}  {fee_str}")


def cmd_tx_log(args, conn):
    if not repository.get_project(conn, args.project):
        _exit_err(f"project not found: {args.project}")
    ch = repository.get_channel(conn, args.channel)
    if not ch:
        _exit_err(f"channel not found: {args.channel}")
    if ch.project_id != args.project:
        _exit_err(f"channel {args.channel} belongs to project '{ch.project_id}', not '{args.project}'")
    occurred = args.date or datetime.now(timezone.utc).isoformat(timespec="seconds")
    t = models.Transaction(
        id=None,
        project_id=args.project,
        channel_id=args.channel,
        occurred_at=occurred,
        gross_amount=args.gross,
        net_amount=args.gross,  # auto-compute on insert if channel has fee rules
        currency=ch.currency,
        kind=args.kind,
        external_id=args.external,
        notes=args.notes,
    )
    tx_id = repository.create_transaction(conn, t)
    if tx_id == 0:
        _ok(f"transaction already imported (external_id={args.external})")
    else:
        _ok(f"tx #{tx_id} logged: gross={t.gross_amount} fee={t.fee_amount} net={t.net_amount}")


def cmd_tx_list(args, conn):
    txs = repository.list_transactions(
        conn,
        project_id=args.project,
        since=_parse_date(args.since),
        until=_parse_date(args.until),
        kind=args.kind,
        limit=args.limit,
    )
    if not txs:
        _ok("no transactions")
        return
    total_net = 0.0
    total_fee = 0.0
    for t in txs:
        print(f"  #{t.id:>4}  {t.occurred_at[:10]}  {t.project_id:30}  {t.kind:9}  "
              f"gross={t.gross_amount:>9.2f}  fee={t.fee_amount:>7.2f}  net={t.net_amount:>9.2f}  {t.currency}")
        total_net += t.net_amount
        total_fee += t.fee_amount
    print(f"  ----  total: net={total_net:.2f}  fees={total_fee:.2f}")


def cmd_metrics(args, conn):
    result = metrics_mod.compute_metrics(conn, project_id=args.project, period=args.period)
    print(json.dumps(result, indent=2, default=str))


def cmd_dashboard(args, conn):
    out = dashboard_mod.render(conn)
    print(out)


def cmd_backup(args, conn):
    path = backup_mod.snapshot(conn, keep=args.keep)
    _ok(f"backup written: {path}")


def cmd_export(args, conn):
    out_path = Path(args.path) if args.path else (Path(db.default_db_path()).parent / "export.json")
    payload = backup_mod.export_json(conn)
    out_path.write_text(payload)
    _ok(f"exported to {out_path}")


def cmd_export_csv(args, conn):
    """Sprint 11: CSV export of transactions or projects."""
    if args.kind == "tx":
        n = csv_export.export_transactions_csv(
            conn, args.path,
            project_id=args.project, since=_parse_date(args.since),
            until=_parse_date(args.until), kind=args.tx_kind,
        )
        _ok(f"wrote {n} transactions to {args.path}")
    elif args.kind == "projects":
        n = csv_export.export_projects_csv(
            conn, args.path,
            status=args.status, category=args.category,
        )
        _ok(f"wrote {n} projects to {args.path}")
    else:
        _exit_err(f"unknown kind: {args.kind}")


def cmd_summary(args, conn):
    """One-line summary: total net, MRR, # projects, # txns."""
    m = metrics_mod.compute_metrics(conn, period="all")
    p_count = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
    a_count = conn.execute("SELECT COUNT(*) FROM projects WHERE status='active'").fetchone()[0]
    t_count = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    print(
        f"projects={p_count} (active={a_count})  txns={t_count}  "
        f"mrr=${m['mrr']:.2f}  arr=${m['arr']:.2f}  "
        f"ytd=${m['ytd_net']:.2f}  total=${m['total_net']:.2f}"
    )


def cmd_seed(args, conn):
    seed_path = Path(args.path) if args.path else (Path(__file__).resolve().parents[2] / "seed" / "seed.json")
    if not seed_path.exists():
        _exit_err(f"seed file not found: {seed_path}")
    count = backup_mod.load_seed(conn, seed_path)
    _ok(f"seeded {count} entities from {seed_path}")


def cmd_integrations(args, conn):
    """Sprint 9 stub: list registered integration connectors and their status."""
    connectors = integrations.list_connectors()
    print("Available integration connectors (no live calls in this loop):")
    for c in connectors:
        status = c.get("configured", False)
        marker = "● configured" if status else "○ stub"
        print(f"  {marker}  {c['name']:12}  {c['platform']:14}  {c['description']}")


def cmd_import_mock(args, conn):
    """Import synthetic NormalizedTxn records from a named connector."""
    ins, skp = integrations.import_mock(conn, args.platform, count=args.count)
    print(f"imported from {args.platform}: inserted={ins} skipped={skp}")


# ---------- arg parser ----------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="asset-tracker", description="Personal side-project + income registry")
    sub = p.add_subparsers(dest="cmd", required=True)

    # project
    pp = sub.add_parser("project", help="Manage projects")
    ppsub = pp.add_subparsers(dest="subcmd", required=True)
    pa = ppsub.add_parser("add", help="Create a project")
    pa.add_argument("id")
    pa.add_argument("--name", required=True)
    pa.add_argument("--category", required=True, choices=sorted(models.VALID_CATEGORIES))
    pa.add_argument("--status", default="active", choices=sorted(models.VALID_STATUSES))
    pa.add_argument("--description")
    pa.add_argument("--tech-stack")
    pa.add_argument("--repo-url")
    pa.add_argument("--repo-local-path")
    pa.set_defaults(func=cmd_project_add)

    pl = ppsub.add_parser("list", help="List projects")
    pl.add_argument("--status", choices=sorted(models.VALID_STATUSES))
    pl.add_argument("--category", choices=sorted(models.VALID_CATEGORIES))
    pl.set_defaults(func=cmd_project_list)

    ps = ppsub.add_parser("show", help="Show one project (JSON)")
    ps.add_argument("id")
    ps.set_defaults(func=cmd_project_show)

    pu = ppsub.add_parser("update", help="Update a project")
    pu.add_argument("id")
    for k in ("name", "category", "status", "description", "tech_stack", "repo_url", "repo_local_path"):
        pu.add_argument(f"--{k.replace('_', '-')}")
    pu.set_defaults(func=cmd_project_update)

    # channel
    ch = sub.add_parser("channel", help="Manage income channels")
    chsub = ch.add_subparsers(dest="subcmd", required=True)
    cha = chsub.add_parser("add", help="Create an income channel")
    cha.add_argument("--project", required=True)
    cha.add_argument("--name", required=True)
    cha.add_argument("--platform", required=True, choices=sorted(models.VALID_PLATFORMS))
    cha.add_argument("--kind", required=True, choices=sorted(models.VALID_KINDS))
    cha.add_argument("--currency", default="USD")
    cha.add_argument("--fee", type=float, help="fee percent (e.g. 10 for 10%)")
    cha.add_argument("--flat", type=float, help="flat fee per transaction")
    cha.add_argument("--active", action="store_true", default=True)
    cha.add_argument("--inactive", dest="active", action="store_false")
    cha.set_defaults(func=cmd_channel_add)

    chl = chsub.add_parser("list", help="List channels")
    chl.add_argument("--project")
    chl.set_defaults(func=cmd_channel_list)

    # transaction
    tx = sub.add_parser("tx", help="Manage transactions")
    txsub = tx.add_subparsers(dest="subcmd", required=True)
    txl = txsub.add_parser("log", help="Log a transaction")
    txl.add_argument("--project", required=True)
    txl.add_argument("--channel", required=True, type=int)
    txl.add_argument("--gross", required=True, type=float)
    txl.add_argument("--kind", required=True, choices=sorted(models.VALID_TX_KINDS))
    txl.add_argument("--date")
    txl.add_argument("--external")
    txl.add_argument("--notes")
    txl.set_defaults(func=cmd_tx_log)

    txls = txsub.add_parser("list", help="List transactions")
    txls.add_argument("--project")
    txls.add_argument("--since")
    txls.add_argument("--until")
    txls.add_argument("--kind", choices=sorted(models.VALID_TX_KINDS))
    txls.add_argument("--limit", type=int, default=100)
    txls.set_defaults(func=cmd_tx_list)

    # metrics / dashboard
    me = sub.add_parser("metrics", help="Compute metrics")
    me.add_argument("--project")
    me.add_argument("--period", default="30d", choices=["30d", "90d", "ytd", "all"])
    me.set_defaults(func=cmd_metrics)

    dash = sub.add_parser("dashboard", help="Render TUI dashboard")
    dash.set_defaults(func=cmd_dashboard)

    # ops
    bk = sub.add_parser("backup", help="Snapshot the database")
    bk.add_argument("--keep", type=int, default=_compat.int_default("AT_BACKUP_KEEP", 7))
    bk.set_defaults(func=cmd_backup)

    ex = sub.add_parser("export", help="Export all data to JSON")
    ex.add_argument("path", nargs="?")
    ex.set_defaults(func=cmd_export)

    cs = sub.add_parser("export-csv", help="Export transactions or projects to CSV (Sprint 11)")
    cs.add_argument("kind", choices=["tx", "projects"])
    cs.add_argument("path")
    cs.add_argument("--project")
    cs.add_argument("--since")
    cs.add_argument("--until")
    cs.add_argument("--tx-kind", choices=sorted(models.VALID_TX_KINDS))
    cs.add_argument("--status", choices=sorted(models.VALID_STATUSES))
    cs.add_argument("--category", choices=sorted(models.VALID_CATEGORIES))
    cs.set_defaults(func=cmd_export_csv)

    sm = sub.add_parser("summary", help="One-line metrics summary")
    sm.set_defaults(func=cmd_summary)

    sd = sub.add_parser("seed", help="Load seed data from JSON")
    sd.add_argument("path", nargs="?")
    sd.set_defaults(func=cmd_seed)

    ig = sub.add_parser("integrations", help="List integration connector stubs")
    ig.set_defaults(func=cmd_integrations)

    im = sub.add_parser("import-mock", help="Import synthetic txns from a connector (Sprint 9)")
    im.add_argument("platform", choices=[c["name"] for c in integrations.list_connectors()])
    im.add_argument("--count", type=int, default=5)
    im.set_defaults(func=cmd_import_mock)

    return p


# ---------- main ----------

def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    conn = db.connect()
    db.init_schema(conn)
    try:
        args.func(args, conn)
        return 0
    except (ValueError, LookupError) as e:
        _exit_err(str(e))
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
