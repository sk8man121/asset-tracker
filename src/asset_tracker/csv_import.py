"""
csv_import.py — Import transactions from CSV files into the NormalizedTxn pipeline.

Supports preset column maps for Bandcamp sales exports and our generic export format.
"""
from __future__ import annotations

import csv
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import integrations
from .integrations import NormalizedTxn, BandcampConnector


# Logical field -> list of acceptable CSV header names (case-insensitive).
PRESETS: dict[str, dict[str, list[str]]] = {
    "bandcamp": {
        "datetime": ["date", "sale date", "datetime", "sold"],
        "item_type": ["item name", "item", "item type", "product"],
        "amount": ["amount", "item price", "price", "net amount"],
        "currency": ["currency"],
        "id": ["paypal transaction id", "transaction id", "id", "sale id"],
        "project_id": ["project_id", "project"],
    },
    "generic": {
        "occurred_at": ["occurred_at", "date"],
        "gross_amount": ["gross_amount", "gross", "amount"],
        "fee_amount": ["fee_amount", "fee"],
        "net_amount": ["net_amount", "net"],
        "currency": ["currency"],
        "kind": ["kind"],
        "external_id": ["external_id", "id"],
        "project_id": ["project_id", "project"],
        "channel_name": ["channel_name", "channel"],
        "notes": ["notes"],
    },
}


def _normalize_header(name: str) -> str:
    return name.strip().lower()


def _resolve_columns(
    fieldnames: list[str],
    preset: dict[str, list[str]],
    overrides: Optional[dict[str, str]] = None,
) -> dict[str, str]:
    """Map logical field names to actual CSV column headers."""
    header_map = {_normalize_header(h): h for h in fieldnames}
    resolved: dict[str, str] = {}

    if overrides:
        for logical, csv_col in overrides.items():
            key = _normalize_header(csv_col)
            if key not in header_map:
                raise ValueError(f"column not found in CSV: {csv_col}")
            resolved[logical] = header_map[key]

    for logical, candidates in preset.items():
        if logical in resolved:
            continue
        for candidate in candidates:
            key = _normalize_header(candidate)
            if key in header_map:
                resolved[logical] = header_map[key]
                break

    return resolved


def _cell(row: dict[str, str], col: Optional[str]) -> str:
    if not col:
        return ""
    return (row.get(col) or "").strip()


def _parse_occurred_at(raw: str) -> str:
    if not raw:
        raise ValueError("missing date")
    if "T" in raw:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    else:
        dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat(timespec="seconds")


def _parse_amount(raw: str) -> float:
    if not raw:
        raise ValueError("missing amount")
    cleaned = raw.replace("$", "").replace(",", "").strip()
    return float(cleaned)


def _row_to_bandcamp(raw_row: dict[str, str], cols: dict[str, str], row_idx: int) -> NormalizedTxn:
    date_raw = _cell(raw_row, cols.get("datetime"))
    amount_raw = _cell(raw_row, cols.get("amount"))
    if not date_raw or not amount_raw:
        raise ValueError("missing required bandcamp fields")

    external_id = _cell(raw_row, cols.get("id")) or f"bc_csv_{row_idx}"
    item_type = _cell(raw_row, cols.get("item_type")) or "Bandcamp sale"
    project_id = _cell(raw_row, cols.get("project_id")) or "unassigned"
    occurred = _parse_occurred_at(date_raw)
    amount = _parse_amount(amount_raw)
    currency = (_cell(raw_row, cols.get("currency")) or "USD").upper()

    connector = BandcampConnector()
    return connector.normalize({
        "id": external_id,
        "datetime": occurred,
        "amount": str(amount),
        "currency": currency,
        "item_type": item_type,
        "project_id": project_id,
    })


def _row_to_generic(raw_row: dict[str, str], cols: dict[str, str], row_idx: int) -> NormalizedTxn:
    occurred_raw = _cell(raw_row, cols.get("occurred_at"))
    gross_raw = _cell(raw_row, cols.get("gross_amount"))
    if not occurred_raw or not gross_raw:
        raise ValueError("missing required generic fields")

    external_id = _cell(raw_row, cols.get("external_id")) or f"csv_{row_idx}"
    fee_raw = _cell(raw_row, cols.get("fee_amount"))
    net_raw = _cell(raw_row, cols.get("net_amount"))
    gross = _parse_amount(gross_raw)
    fee = _parse_amount(fee_raw) if fee_raw else 0.0
    net = _parse_amount(net_raw) if net_raw else None

    return NormalizedTxn(
        external_id=external_id,
        project_id=_cell(raw_row, cols.get("project_id")) or "unassigned",
        channel_name=_cell(raw_row, cols.get("channel_name")) or "CSV import",
        occurred_at=_parse_occurred_at(occurred_raw),
        gross_amount=gross,
        fee_amount=fee,
        net_amount=net,
        currency=(_cell(raw_row, cols.get("currency")) or "USD").upper(),
        kind=_cell(raw_row, cols.get("kind")) or "one_time",
        notes=_cell(raw_row, cols.get("notes")) or None,
    )


def parse_csv_rows(
    path: Path,
    *,
    platform: str = "generic",
    column_map: Optional[dict[str, str]] = None,
) -> tuple[list[NormalizedTxn], int]:
    """Parse a CSV file into NormalizedTxn rows. Returns (txns, rejected_count)."""
    if platform not in PRESETS:
        raise ValueError(f"unknown CSV platform preset: {platform}")

    if not path.is_file():
        raise FileNotFoundError(f"CSV file not found: {path}")

    txns: list[NormalizedTxn] = []
    rejected = 0

    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            raise ValueError("CSV has no header row")
        cols = _resolve_columns(list(reader.fieldnames), PRESETS[platform], column_map)

        for idx, row in enumerate(reader, start=1):
            try:
                if platform == "bandcamp":
                    txns.append(_row_to_bandcamp(row, cols, idx))
                else:
                    txns.append(_row_to_generic(row, cols, idx))
            except (ValueError, TypeError, KeyError):
                rejected += 1

    return txns, rejected


def import_csv(
    conn: sqlite3.Connection,
    path: Path,
    *,
    platform: str = "generic",
    project_resolver: Optional[dict[str, str]] = None,
    column_map: Optional[dict[str, str]] = None,
) -> tuple[int, int, int]:
    """Parse CSV and import via import_normalized. Returns (inserted, skipped, rejected)."""
    txns, rejected = parse_csv_rows(path, platform=platform, column_map=column_map)
    platform_id = "bandcamp" if platform == "bandcamp" else "other"
    inserted, skipped = integrations.import_normalized(
        conn, txns, project_resolver, platform_id=platform_id,
    )
    if inserted > 0:
        from . import config
        config.record_sync(f"csv:{platform}")
    return inserted, skipped, rejected
