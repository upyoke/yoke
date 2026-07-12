"""Bounded secret scrubbing for untrusted Git subprocess diagnostics."""

from __future__ import annotations

import base64
import json
import re
import urllib.parse
from typing import Iterable

from yoke_cli.config import github_response_safety


MAX_GIT_DIAGNOSTIC_CHARS = 2_000
REDACTED_GIT_SECRET = "[redacted]"


def scrub_git_diagnostic(value: object, *, token: str | None = None) -> str:
    """Redact every known wire rendering of a token, then cap the result."""

    text = str(value or "")
    secrets = _secret_renderings(token) if token else ()
    for secret in sorted(secrets, key=len, reverse=True):
        if secret:
            text = re.sub(
                re.escape(secret), REDACTED_GIT_SECRET, text,
                flags=re.IGNORECASE,
            )
    text = re.sub(
        r"authorization(?:\\u003a|%3a|\s*:)\s*"
        r"(?:basic|bearer)\s+[A-Za-z0-9._~+/=%-]+",
        f"Authorization: {REDACTED_GIT_SECRET}",
        text,
        flags=re.IGNORECASE,
    )
    return github_response_safety.terminal_safe_text(
        text, maximum_chars=MAX_GIT_DIAGNOSTIC_CHARS,
    )


def _secret_renderings(token: str) -> Iterable[str]:
    basic_input = f"x-access-token:{token}"
    encoded = base64.b64encode(basic_input.encode("utf-8")).decode("ascii")
    header = f"AUTHORIZATION: basic {encoded}"
    values = {token, basic_input, encoded, header}
    for value in tuple(values):
        values.add(urllib.parse.quote(value, safe=""))
        values.add(urllib.parse.quote_plus(value, safe=""))
        values.add(json.dumps(value)[1:-1])
    return values


__all__ = [
    "MAX_GIT_DIAGNOSTIC_CHARS",
    "REDACTED_GIT_SECRET",
    "scrub_git_diagnostic",
]
