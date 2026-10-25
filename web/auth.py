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
