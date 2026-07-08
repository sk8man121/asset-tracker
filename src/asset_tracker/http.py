"""
http.py — Minimal stdlib HTTP helpers for live integrations.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

# Query param names that must never appear in exception messages / logs.
_SECRET_QUERY_KEYS = frozenset({
    "access_token", "token", "key", "api_key", "apikey", "secret",
    "password", "authorization", "auth",
})


def redact_url(url: str) -> str:
    """Return a copy of *url* with secret query params replaced by 'REDACTED'."""
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return "<unparseable-url>"
    if not parts.query:
        return url
    pairs = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    redacted = [
        (k, "REDACTED" if k.lower() in _SECRET_QUERY_KEYS else v)
        for k, v in pairs
    ]
    return urllib.parse.urlunsplit((
        parts.scheme, parts.netloc, parts.path,
        urllib.parse.urlencode(redacted), parts.fragment,
    ))


class HttpError(RuntimeError):
    def __init__(self, status: int, body: str, url: str):
        safe_url = redact_url(url)
        super().__init__(f"HTTP {status} from {safe_url}: {body[:200]}")
        self.status = status
        self.body = body
        self.url = safe_url


def post_json(
    url: str,
    *,
    headers: Optional[dict[str, str]] = None,
    body: Optional[dict[str, Any]] = None,
    timeout: int = 30,
) -> dict:
    """POST request with JSON body, return parsed JSON. Raises HttpError on non-2xx."""
    data = json.dumps(body or {}).encode("utf-8")
    req_headers = {"Content-Type": "application/json", **(headers or {})}
    req = urllib.request.Request(url, data=data, headers=req_headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise HttpError(e.code, err_body, url) from e


def get_json(
    url: str,
    *,
    headers: Optional[dict[str, str]] = None,
    params: Optional[dict[str, Any]] = None,
    timeout: int = 30,
) -> dict:
    """GET request, return parsed JSON. Raises HttpError on non-2xx."""
    if params:
        query = urllib.parse.urlencode(params, doseq=True)
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}{query}"
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise HttpError(e.code, body, url) from e
