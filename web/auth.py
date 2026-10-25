"""Bearer-token authentication for the WebUI.

The token comes from `TP_WEB_TOKEN` (or the `--token` flag). When no token is
configured the API is open, which is acceptable only on loopback; the entry
point refuses to start on a non-loopback host without a token.
"""
from __future__ import annotations

import hmac
import ipaddress
import os
from typing import Optional

TOKEN_ENV = "TP_WEB_TOKEN"
SESSION_COOKIE = "tp_session"


def token_from_env() -> Optional[str]:
    value = (os.environ.get(TOKEN_ENV) or "").strip()
    return value or None


def is_loopback(host: str) -> bool:
    if host in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def token_matches(provided: str, expected: str) -> bool:
    return hmac.compare_digest(provided or "", expected or "")


def request_token(request) -> str:
    """Token from the bearer header, the SSE query parameter or the session cookie."""
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:]
    query = request.query_params.get("token", "")
    if query:
        return query
    return request.cookies.get(SESSION_COOKIE, "")
