"""
_compat.py — Internal compat helpers used by cli.py.
"""
import os
import sys

def int_default(env_name: str, default: int) -> int:
    try:
        return int(os.environ.get(env_name, default))
    except (TypeError, ValueError):
        return default
