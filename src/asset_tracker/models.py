"""
models.py — dataclasses that mirror the SQLite schema + (de)serialization helpers.

Pure stdlib. No external deps.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional


# ---------- enums (kept as plain strings, validated at I/O boundary) ----------

VALID_CATEGORIES = {"software", "music", "creative", "content", "physical", "service"}
VALID_STATUSES = {"active", "dormant", "archived", "idea"}
VALID_PLATFORMS = {"gumroad", "stripe", "bandcamp", "etsy", "github_sponsors", "direct", "other"}
VALID_KINDS = {"recurring", "one_time", "royalty", "tip"}
VALID_TX_KINDS = VALID_KINDS | {"refund"}


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------- entities ----------

@dataclass
class Project:
    id: str
    name: str
    category: str
    status: str
    created_at: str = field(default_factory=_utcnow_iso)
    description: Optional[str] = None
    started_at: Optional[str] = None
    tech_stack: Optional[str] = None
    repo_url: Optional[str] = None
    repo_local_path: Optional[str] = None
    time_to_first_income_days: Optional[int] = None
    notes: Optional[str] = None

    def validate(self) -> list[str]:
        errs = []
        if not self.id or not self.id.strip():
            errs.append("id required")
        if not self.name or not self.name.strip():
            errs.append("name required")
        if self.category not in VALID_CATEGORIES:
            errs.append(f"category {self.category!r} not in {VALID_CATEGORIES}")
        if self.status not in VALID_STATUSES:
            errs.append(f"status {self.status!r} not in {VALID_STATUSES}")
        return errs

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_row(cls, row) -> "Project":
        return cls(**dict(row))


@dataclass
class IncomeChannel:
    id: Optional[int]
    project_id: str
    name: str
    platform: str
    kind: str
    currency: str = "USD"
    fee_pct: float = 0.0
    fee_flat: float = 0.0
    active: int = 1
    created_at: str = field(default_factory=_utcnow_iso)

    def validate(self) -> list[str]:
        errs = []
        if not self.name:
            errs.append("name required")
        if self.platform not in VALID_PLATFORMS:
            errs.append(f"platform {self.platform!r} not in {VALID_PLATFORMS}")
        if self.kind not in VALID_KINDS:
            errs.append(f"kind {self.kind!r} not in {VALID_KINDS}")
        if not self.currency or len(self.currency) != 3:
            errs.append("currency must be 3-char ISO 4217")
        if self.active not in (0, 1):
            errs.append("active must be 0 or 1")
        return errs

    def compute_fee(self, gross: float) -> float:
        return round(gross * self.fee_pct + self.fee_flat, 2)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_row(cls, row) -> "IncomeChannel":
        return cls(**dict(row))


@dataclass
class Transaction:
    id: Optional[int]
    project_id: str
    channel_id: int
    occurred_at: str
    gross_amount: float
    net_amount: float
    currency: str
    kind: str
    fee_amount: float = 0.0
    external_id: Optional[str] = None
    notes: Optional[str] = None

    def validate(self) -> list[str]:
        errs = []
        if self.gross_amount < 0:
            errs.append("gross_amount must be ≥ 0")
        if self.net_amount < 0:
            errs.append("net_amount must be ≥ 0")
        if self.fee_amount < 0:
            errs.append("fee_amount must be ≥ 0")
        if self.kind not in VALID_TX_KINDS:
            errs.append(f"kind {self.kind!r} not in {VALID_TX_KINDS}")
        if not self.currency or len(self.currency) != 3:
            errs.append("currency must be 3-char ISO 4217")
        # Refunds: net should be ≤ 0 (returning money). Other kinds: net > 0.
        if self.kind == "refund" and self.net_amount > 0:
            errs.append("refund transactions must have net_amount ≤ 0")
        elif self.kind != "refund" and self.net_amount <= 0:
            errs.append("non-refund transactions must have net_amount > 0")
        return errs

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_row(cls, row) -> "Transaction":
        return cls(**dict(row))


@dataclass
class TimeLog:
    id: Optional[int]
    project_id: str
    started_at: str
    ended_at: str
    minutes: int
    notes: Optional[str] = None

    def validate(self) -> list[str]:
        errs = []
        if self.minutes < 0:
            errs.append("minutes must be ≥ 0")
        if self.minutes > 60 * 24 * 30:
            errs.append("minutes exceeds 30-day plausible max")
        return errs

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_row(cls, row) -> "TimeLog":
        return cls(**dict(row))


# ---------- export ----------

def export_all(payload: dict) -> str:
    """Serialize a dict of {table_name: [rows, ...]} to pretty JSON."""
    return json.dumps(payload, indent=2, default=str)
