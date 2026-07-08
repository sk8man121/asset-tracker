"""
cli.py — argparse-based CLI for asset-tracker.

Daily workflow:
    asset-tracker init              # first-run setup
    asset-tracker log 49.99         # quick income log (uses config defaults)
    asset-tracker time log --minutes 90
    asset-tracker summary           # morning check-in
    asset-tracker dashboard         # full view
    asset-tracker doctor            # health check
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import __version__

from . import config, db, models, onboard, repository
from . import metrics as metrics_mod
from . import dashboard as dashboard_mod
from . import backup as backup_mod
from . import integrations
from . import csv_import
from . import _compat
from . import csv_export
from . import report as report_mod


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


def _window_from_since(since: str, until: str | None = None) -> tuple[str, str]:
    """Resolve --since (30d|90d|ytd|all|YYYY-MM-DD) to ISO window."""
    if since in ("30d", "90d", "ytd", "all"):
        start, end = metrics_mod._period_window(since)
        start_iso = start.isoformat(timespec="seconds")
        end_iso = end.isoformat(timespec="seconds")
    else:
        start_iso = _parse_date(since) or since
        end_iso = _parse_date(until) if until else datetime.now(timezone.utc).isoformat(timespec="seconds")
    return start_iso, end_iso


def _resolve_project(conn, explicit: str | None) -> str:
    if explicit:
        if not repository.get_project(conn, explicit):
            _exit_err(f"project not found: {explicit}")
        return explicit
    default = config.get_default("default_project")
    if default:
        if not repository.get_project(conn, default):
            _exit_err(f"default_project '{default}' not found — run `asset-tracker init` or update config")
        return default
    projects = repository.list_projects(conn)
    if len(projects) == 1:
        config.set_defaults(default_project=projects[0].id)
        return projects[0].id
    if not projects:
        _exit_err("no projects yet — run `asset-tracker init`")
    ids = ", ".join(p.id for p in projects[:5])
    _exit_err(f"--project required (or set default_project in config). Projects: {ids}")


def _resolve_channel_ref(conn, project_id: str, explicit: str | None) -> models.IncomeChannel:
    ref = explicit or config.get_default("default_channel")
    if not ref:
        channels = repository.list_channels(conn, project_id=project_id)
        if len(channels) == 1:
            return channels[0]
        if not channels:
            _exit_err(
                f"no channels for '{project_id}' — run: "
                f"asset-tracker channel add --project {project_id} --name \"Sales\" --platform direct --kind one_time"
            )
        names = ", ".join(f"'{c.name}'" for c in channels)
        _exit_err(f"--channel required. Available for '{project_id}': {names}")
    try:
        return repository.resolve_channel(conn, project_id, ref)
    except LookupError as e:
        _exit_err(str(e))


# ---------- subcommand builders ----------

def cmd_init(args, conn):
    if args.seed:
        msg = onboard.run_init(conn, interactive=False, from_seed=True, seed_path=Path(args.seed) if args.seed != "default" else None)
    elif args.project_id:
        msg = onboard.run_init(
            conn, interactive=False,
            project_id=args.project_id, project_name=args.project_name or args.project_id,
            category=args.category,
        )
    else:
        msg = onboard.run_init(conn, interactive=not args.yes)
    _ok(msg)


def cmd_doctor(args, conn):
    print(onboard.run_doctor(conn))


def cmd_log(args, conn):
    """Quick daily income log — minimal flags when defaults are configured."""
    project_id = _resolve_project(conn, args.project)
    ch = _resolve_channel_ref(conn, project_id, args.channel)
    if not config.get_default("default_project"):
        config.set_defaults(default_project=project_id)
    if args.channel and not config.get_default("default_channel"):
        config.set_defaults(default_channel=args.channel)

    occurred = _parse_date(args.date) or datetime.now(timezone.utc).isoformat(timespec="seconds")
    kind = args.kind or ch.kind
    t = models.Transaction(
        id=None,
        project_id=project_id,
        channel_id=ch.id,
        occurred_at=occurred,
        gross_amount=args.amount,
        net_amount=args.amount,
        currency=ch.currency,
        kind=kind,
        external_id=args.external,
        notes=args.notes,
    )
    tx_id = repository.create_transaction(conn, t)
    if tx_id == 0:
        _ok(f"already logged (external_id={args.external})")
    else:
        _ok(
            f"logged ${t.gross_amount:.2f} → net ${t.net_amount:.2f} "
            f"on '{ch.name}' ({project_id})"
        )


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
    project_id = _resolve_project(conn, args.project)
    ch = _resolve_channel_ref(conn, project_id, args.channel)
    occurred = _parse_date(args.date) or datetime.now(timezone.utc).isoformat(timespec="seconds")
    kind = args.kind or ch.kind
    t = models.Transaction(
        id=None,
        project_id=project_id,
        channel_id=ch.id,
        occurred_at=occurred,
        gross_amount=args.gross,
        net_amount=args.gross,
        currency=ch.currency,
        kind=kind,
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


def cmd_time_log(args, conn):
    project_id = _resolve_project(conn, args.project)
    now = datetime.now(timezone.utc)
    if args.date:
        started = datetime.fromisoformat(_parse_date(args.date))
    else:
        started = now
    ended = started + timedelta(minutes=args.minutes)
    tl = models.TimeLog(
        id=None,
        project_id=project_id,
        started_at=started.isoformat(timespec="seconds"),
        ended_at=ended.isoformat(timespec="seconds"),
        minutes=args.minutes,
        notes=args.notes,
    )
    tid = repository.create_time_log(conn, tl)
    hours = args.minutes / 60.0
    _ok(f"time #{tid} logged: {hours:.1f}h on '{project_id}'")


def cmd_time_list(args, conn):
    logs = repository.list_time_logs(conn, project_id=args.project)
    if not logs:
        _ok("no time logs")
        return
    total = 0
    for tl in logs[:args.limit]:
        hours = tl.minutes / 60.0
        total += tl.minutes
        note = f"  {tl.notes}" if tl.notes else ""
        print(f"  #{tl.id:>4}  {tl.started_at[:10]}  {tl.project_id:30}  {hours:>6.1f}h{note}")
    print(f"  ----  total: {total / 60.0:.1f}h ({len(logs)} entries)")


def _format_currency_summary(by_currency: list[dict]) -> str:
    if not by_currency:
        return ""
    if len(by_currency) == 1:
        c = by_currency[0]["currency"]
        return f"mrr={c} {by_currency[0]['mrr']:.2f}  arr={c} {by_currency[0]['arr']:.2f}  " \
               f"ytd={c} {by_currency[0]['ytd_net']:.2f}  total={c} {by_currency[0]['total_net']:.2f}"
    parts = []
    for row in by_currency:
        c = row["currency"]
        parts.append(f"{c} mrr={row['mrr']:.2f} ytd={row['ytd_net']:.2f} total={row['total_net']:.2f}")
    return "  ".join(parts)


def cmd_recent(args, conn):
    """Show activity for the last N days — quick weekly review."""
    since = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat(timespec="seconds")
    until = datetime.now(timezone.utc).isoformat(timespec="seconds")
    txs = repository.list_transactions(conn, since=since, limit=1000)
    txs_show = txs[:args.limit]
    logs = [tl for tl in repository.list_time_logs(conn) if tl.started_at >= since]
    logs_show = logs[:args.limit]
    by_curr: dict[str, float] = {}
    for t in txs:
        by_curr[t.currency] = by_curr.get(t.currency, 0.0) + t.net_amount
    if len(by_curr) <= 1:
        currency = next(iter(by_curr), "USD")
        period_net = by_curr.get(currency, 0.0)
        net_label = f"net={currency} {period_net:.2f}"
    else:
        net_label = "net=" + " ".join(f"{c} {v:.2f}" for c, v in sorted(by_curr.items()))
    hours = sum(tl.minutes for tl in logs) / 60.0
    print(f"Last {args.days} days  ·  {net_label}  ·  {len(txs)} txns  ·  {hours:.1f}h logged")

    by_project = report_mod.summarize_window(conn, since, until)
    if by_project:
        print("\nBy project:")
        for row in by_project:
            print(
                f"  {row['project_id']:24}  {row['currency']} {row['net']:>8.2f}  "
                f"({row['tx_count']} txn{'s' if row['tx_count'] != 1 else ''})"
            )

    if txs_show:
        print("\nTransactions:")
        for t in txs_show:
            print(f"  {t.occurred_at[:10]}  {t.project_id:24}  ${t.net_amount:>8.2f}  {t.kind}")
        if len(txs) > len(txs_show):
            print(f"  … and {len(txs) - len(txs_show)} more")
    if logs_show:
        print("\nTime:")
        for tl in logs_show:
            print(f"  {tl.started_at[:10]}  {tl.project_id:24}  {tl.minutes/60:>5.1f}h  {tl.notes or ''}")
    if not txs and not logs:
        print("  (no activity in this window)")


def _parse_column_overrides(specs: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for spec in specs:
        if "=" not in spec:
            _exit_err(f"invalid --column (expected field=Header): {spec}")
        key, _, val = spec.partition("=")
        key, val = key.strip(), val.strip()
        if not key or not val:
            _exit_err(f"invalid --column (expected field=Header): {spec}")
        out[key] = val
    return out


def cmd_import_live(args, conn):
    if not os.environ.get("AT_LIVE_INTEGRATIONS"):
        _exit_err("live imports require AT_LIVE_INTEGRATIONS=1 in .env")
    since_iso, until_iso = _window_from_since(args.since, args.until)
    if args.project and not repository.get_project(conn, args.project):
        _exit_err(f"project not found: {args.project}")
    resolver = config.build_project_resolver(override_project=args.project)
    ins, skp = integrations.import_live(
        conn, args.platform, since_iso, until_iso, project_resolver=resolver,
    )
    print(f"imported from {args.platform}: inserted={ins} skipped={skp} (window: {since_iso[:10]} → {until_iso[:10]})")


def cmd_import_csv(args, conn):
    path = Path(args.file)
    if args.project and not repository.get_project(conn, args.project):
        _exit_err(f"project not found: {args.project}")
    resolver = config.build_project_resolver(override_project=args.project)
    column_map = _parse_column_overrides(args.column) if args.column else None
    ins, skp, rejected = csv_import.import_csv(
        conn, path,
        platform=args.platform,
        project_resolver=resolver,
        column_map=column_map,
    )
    print(
        f"imported from {path.name} ({args.platform}): "
        f"inserted={ins} skipped={skp} rejected={rejected}"
    )


def cmd_import_sync(args, conn):
    if not os.environ.get("AT_LIVE_INTEGRATIONS"):
        _exit_err("live imports require AT_LIVE_INTEGRATIONS=1 in .env")
    since_iso, until_iso = _window_from_since(args.since, args.until)
    if args.project and not repository.get_project(conn, args.project):
        _exit_err(f"project not found: {args.project}")
    resolver = config.build_project_resolver(override_project=args.project)
    results = integrations.import_sync(conn, since_iso, until_iso, project_resolver=resolver)
    if not results:
        print("no configured platforms to sync — set API keys in .env")
        return
    print(f"sync complete (window: {since_iso[:10]} → {until_iso[:10]}):")
    for platform, outcome in sorted(results.items()):
        if isinstance(outcome, tuple):
            ins, skp = outcome
            print(f"  {platform:16}  inserted={ins} skipped={skp}")
        else:
            print(f"  {platform:16}  {outcome}")


def cmd_report(args, conn):
    report = report_mod.build_report(
        conn,
        period=args.period,
        compare=not args.no_compare,
        project_id=args.project,
    )
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(report_mod.format_report(report))


def cmd_metrics(args, conn):
    result = metrics_mod.compute_metrics(conn, project_id=args.project, period=args.period)
    print(json.dumps(result, indent=2, default=str))


def cmd_dashboard(args, conn):
    out = dashboard_mod.render(conn, period=args.period, compare=args.compare)
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
    elif args.kind == "rollup":
        n = csv_export.export_rollup_csv(conn, args.path, year=args.year)
        _ok(f"wrote {n} rollup rows to {args.path}")
    else:
        _exit_err(f"unknown kind: {args.kind}")


def cmd_summary(args, conn):
    m = metrics_mod.compute_metrics(conn, period="all")
    p_count = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
    a_count = conn.execute("SELECT COUNT(*) FROM projects WHERE status='active'").fetchone()[0]
    t_count = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    last_tx = conn.execute(
        "SELECT occurred_at FROM transactions ORDER BY occurred_at DESC LIMIT 1"
    ).fetchone()
    last_str = last_tx["occurred_at"][:10] if last_tx else "never"
    metrics_line = _format_currency_summary(m.get("by_currency", []))
    print(
        f"projects={p_count} (active={a_count})  txns={t_count}  "
        f"{metrics_line}  last_txn={last_str}"
    )
    if not onboard.is_initialized(conn):
        print("→ run `asset-tracker init` to get started", file=sys.stderr)


def cmd_seed(args, conn):
    seed_path = Path(args.path) if args.path else (Path(__file__).resolve().parents[2] / "seed" / "seed.json")
    if not seed_path.exists():
        _exit_err(f"seed file not found: {seed_path}")
    count = backup_mod.load_seed(conn, seed_path)
    first = conn.execute("SELECT id FROM projects ORDER BY created_at LIMIT 1").fetchone()
    if first:
        config.set_defaults(default_project=first["id"])
    _ok(f"seeded {count} entities from {seed_path}")


def cmd_integrations(args, conn):
    connectors = integrations.list_connectors()
    live = bool(os.environ.get("AT_LIVE_INTEGRATIONS"))
    print(f"Integration connectors (live={'on' if live else 'off'}):")
    for c in connectors:
        conn_obj = integrations.get_connector(c["name"])
        ok, msg = conn_obj.verify()
        marker = "● ready" if ok and c["configured"] else ("○ configured" if c["configured"] else "○ stub")
        print(f"  {marker}  {c['name']:14}  {c['platform']:16}  {msg}")


def cmd_import_mock(args, conn):
    ins, skp = integrations.import_mock(conn, args.platform, count=args.count)
    print(f"imported from {args.platform}: inserted={ins} skipped={skp}")


def cmd_config_show(args, conn):
    cfg = config.load_config()
    cfg["_path"] = str(config.config_path())
    cfg["_db"] = str(db.default_db_path())
    print(json.dumps(cfg, indent=2))


def cmd_config_set(args, conn):
    if args.default_project is None and args.default_channel is None:
        _exit_err("specify --default-project and/or --default-channel")
    config.set_defaults(default_project=args.default_project, default_channel=args.default_channel)
    _ok(f"config saved to {config.config_path()}")


# ---------- arg parser ----------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="asset-tracker",
        description="Personal side-project + income registry",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    # init / doctor — daily essentials
    ini = sub.add_parser("init", help="First-run setup wizard")
    ini.add_argument("--seed", nargs="?", const="default", help="Load demo seed data instead of wizard")
    ini.add_argument("--yes", action="store_true", help="Non-interactive wizard (requires --project-id)")
    ini.add_argument("--project-id")
    ini.add_argument("--project-name")
    ini.add_argument("--category", default="software", choices=sorted(models.VALID_CATEGORIES))
    ini.set_defaults(func=cmd_init)

    doc = sub.add_parser("doctor", help="Health check and setup guidance")
    doc.set_defaults(func=cmd_doctor)

    rc = sub.add_parser("recent", help="Activity digest for the last N days")
    rc.add_argument("--days", type=int, default=7)
    rc.add_argument("--limit", type=int, default=15)
    rc.set_defaults(func=cmd_recent)

    rp = sub.add_parser("report", help="Period report with optional comparison")
    rp.add_argument("--period", default="30d", choices=sorted(metrics_mod.VALID_PERIODS))
    rp.add_argument("--project")
    rp.add_argument("--json", action="store_true", help="Emit JSON instead of TUI")
    rp.add_argument("--no-compare", action="store_true", help="Current period only")
    rp.set_defaults(func=cmd_report)

    # quick log — the daily workhorse
    lg = sub.add_parser("log", help="Quick income log (uses config defaults)")
    lg.add_argument("amount", type=float, help="Gross amount in channel currency")
    lg.add_argument("--project", help="Project id (default: config default_project)")
    lg.add_argument("--channel", help="Channel name, platform, or id (default: config default_channel)")
    lg.add_argument("--kind", choices=sorted(models.VALID_TX_KINDS), help="Override transaction kind")
    lg.add_argument("--date", help="YYYY-MM-DD or ISO timestamp")
    lg.add_argument("--external", help="External id for idempotent import")
    lg.add_argument("--notes")
    lg.set_defaults(func=cmd_log)

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
    txl = txsub.add_parser("log", help="Log a transaction (explicit flags)")
    txl.add_argument("--project", help="Project id (default: config default_project)")
    txl.add_argument("--channel", help="Channel id, name, or platform (default: config)")
    txl.add_argument("--gross", required=True, type=float)
    txl.add_argument("--kind", choices=sorted(models.VALID_TX_KINDS), help="Defaults to channel kind")
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

    # time tracking
    tm = sub.add_parser("time", help="Track time spent on projects")
    tmsub = tm.add_subparsers(dest="subcmd", required=True)
    tml = tmsub.add_parser("log", help="Log time on a project")
    tml.add_argument("--minutes", required=True, type=int, help="Minutes spent")
    tml.add_argument("--project", help="Project id (default: config default_project)")
    tml.add_argument("--date", help="YYYY-MM-DD (defaults to today)")
    tml.add_argument("--notes")
    tml.set_defaults(func=cmd_time_log)

    tmls = tmsub.add_parser("list", help="List time logs")
    tmls.add_argument("--project")
    tmls.add_argument("--limit", type=int, default=50)
    tmls.set_defaults(func=cmd_time_list)

    # metrics / dashboard
    me = sub.add_parser("metrics", help="Compute metrics")
    me.add_argument("--project")
    me.add_argument("--period", default="30d", choices=sorted(metrics_mod.VALID_PERIODS))
    me.set_defaults(func=cmd_metrics)

    dash = sub.add_parser("dashboard", help="Render TUI dashboard")
    dash.add_argument("--period", default="30d", choices=sorted(metrics_mod.VALID_PERIODS))
    dash.add_argument("--compare", action="store_true", help="Show period net delta vs prior window")
    dash.set_defaults(func=cmd_dashboard)

    # ops
    bk = sub.add_parser("backup", help="Snapshot the database")
    bk.add_argument("--keep", type=int, default=_compat.int_default("AT_BACKUP_KEEP", 7))
    bk.set_defaults(func=cmd_backup)

    ex = sub.add_parser("export", help="Export all data to JSON")
    ex.add_argument("path", nargs="?")
    ex.set_defaults(func=cmd_export)

    cs = sub.add_parser("export-csv", help="Export transactions, projects, or rollup to CSV")
    cs.add_argument("kind", choices=["tx", "projects", "rollup"])
    cs.add_argument("path")
    cs.add_argument("--project")
    cs.add_argument("--since")
    cs.add_argument("--until")
    cs.add_argument("--year", type=int, help="Calendar year for rollup export (default: current year)")
    cs.add_argument("--tx-kind", choices=sorted(models.VALID_TX_KINDS))
    cs.add_argument("--status", choices=sorted(models.VALID_STATUSES))
    cs.add_argument("--category", choices=sorted(models.VALID_CATEGORIES))
    cs.set_defaults(func=cmd_export_csv)

    sm = sub.add_parser("summary", help="One-line metrics summary")
    sm.set_defaults(func=cmd_summary)

    sd = sub.add_parser("seed", help="Load seed data from JSON")
    sd.add_argument("path", nargs="?")
    sd.set_defaults(func=cmd_seed)

    ig = sub.add_parser("integrations", help="List integration connectors")
    ig.set_defaults(func=cmd_integrations)

    im = sub.add_parser("import-mock", help="Import synthetic txns from a connector")
    im.add_argument("platform", choices=[c["name"] for c in integrations.list_connectors()])
    im.add_argument("--count", type=int, default=5)
    im.set_defaults(func=cmd_import_mock)

    imp = sub.add_parser("import", help="Import transactions (live, CSV, or sync)")
    impsub = imp.add_subparsers(dest="import_sub", required=True)

    csv_imp = impsub.add_parser("csv", help="Import transactions from a CSV file")
    csv_imp.add_argument("file", help="Path to CSV file")
    csv_imp.add_argument("--platform", default="generic", choices=sorted(csv_import.PRESETS.keys()))
    csv_imp.add_argument("--project", help="Force all imported txns to this local project id")
    csv_imp.add_argument(
        "--column", action="append", default=[],
        help="Override column mapping: logical_field=CSV Header (repeatable)",
    )
    csv_imp.set_defaults(func=cmd_import_csv)

    sync_imp = impsub.add_parser("sync", help="Import from all configured live platforms")
    sync_imp.add_argument("--since", default="30d", help="30d|90d|ytd|all|YYYY-MM-DD")
    sync_imp.add_argument("--until", help="YYYY-MM-DD (default: now)")
    sync_imp.add_argument("--project", help="Force all imported txns to this local project id")
    sync_imp.set_defaults(func=cmd_import_sync)

    for c in integrations.REGISTRY:
        lp = impsub.add_parser(
            c.platform_id,
            help=f"Import live transactions from {c.platform_name}",
        )
        lp.add_argument("--since", default="30d", help="30d|90d|ytd|all|YYYY-MM-DD")
        lp.add_argument("--until", help="YYYY-MM-DD (default: now)")
        lp.add_argument("--project", help="Force all imported txns to this local project id")
        lp.set_defaults(func=cmd_import_live, platform=c.platform_id)

    # config
    cf = sub.add_parser("config", help="View or set local defaults")
    cfsub = cf.add_subparsers(dest="subcmd", required=True)
    cfs = cfsub.add_parser("show", help="Show current config")
    cfs.set_defaults(func=cmd_config_show)
    cfset = cfsub.add_parser("set", help="Set default project/channel")
    cfset.add_argument("--default-project")
    cfset.add_argument("--default-channel")
    cfset.set_defaults(func=cmd_config_set)

    return p


# ---------- main ----------

def main(argv: list[str] | None = None) -> int:
    config.load_dotenv()
    level_name = os.environ.get("AT_LOG_LEVEL", "WARNING").upper()
    level = getattr(logging, level_name, logging.WARNING)
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")
    parser = build_parser()
    args = parser.parse_args(argv)
    conn = db.connect()
    db.init_schema(conn)
    try:
        args.func(args, conn)
        return 0
    except (ValueError, LookupError, RuntimeError) as e:
        _exit_err(str(e))
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
