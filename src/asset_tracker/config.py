"""
config.py — Local settings and environment bootstrap.

Loads (in order):
  1. `.env` from repo root (if present) — simple KEY=VALUE, no external deps
  2. `.asset-tracker.json` adjacent to the database file

Config keys:
  default_project  — used when --project is omitted on quick commands
  default_channel  — channel name, platform, or numeric id string
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from . import db


def load_dotenv(path: Optional[Path] = None) -> None:
    """Parse a .env file into os.environ (only sets keys not already set)."""
    env_path = path or (db.REPO_ROOT / ".env")
    if not env_path.is_file():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


def config_path() -> Path:
    """Config file lives next to the database."""
    return db.default_db_path().parent / ".asset-tracker.json"


def load_config() -> dict[str, Any]:
    path = config_path()
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save_config(data: dict[str, Any]) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")
    return path


def get_default(key: str, fallback: Optional[str] = None) -> Optional[str]:
    val = load_config().get(key)
    if val is not None and str(val).strip():
        return str(val).strip()
    return fallback


def set_defaults(default_project: Optional[str] = None, default_channel: Optional[str] = None) -> Path:
    cfg = load_config()
    if default_project is not None:
        cfg["default_project"] = default_project
    if default_channel is not None:
        cfg["default_channel"] = default_channel
    return save_config(cfg)


def get_import_project_map() -> dict[str, str]:
    """Return {external_or_import_id: local_project_id} from config."""
    raw = load_config().get("import_project_map")
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items() if k and v}


def build_project_resolver(
    *,
    override_project: Optional[str] = None,
    config_map: Optional[dict[str, str]] = None,
) -> dict[str, str]:
    """Merge config import map with optional CLI --project override."""
    resolver = dict(config_map or get_import_project_map())
    if override_project:
        resolver["__force__"] = override_project
    return resolver
