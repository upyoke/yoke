"""One bounded JSON read over HTTPS, shared by every plan-limit probe.

Vendors answer plan questions over HTTPS, and every probe wants the same
three outcomes from that call: the document, a named credential problem, or
a named transport problem. Returning a reason string instead of raising
keeps each probe's failure taxonomy in one place rather than in a chain of
except clauses.

Diagnostic rule for this whole usage-probe path (Claude and Cursor here, the
Codex usage mirror below, and the JSON-RPC-based Codex app-server client
alongside it): preserve the vendor's actual error when wrapping or
categorizing a failure — keep its safe code, message, and other useful
detail rather than collapsing it into a reason built for a different,
unrelated failure. Redact credentials and sensitive request values before a
message is surfaced. A short reason string is still a category, not an
invented cause: assert only what the upstream error actually establishes,
and reserve an "unsupported" reading for an explicit unsupported-operation
response — never a stand-in for "the call failed for some other reason"
(field-note 46471).
"""

from __future__ import annotations

import json
from typing import Any, Mapping
import urllib.error
import urllib.request


PLAN_LIMIT_PROBE_TIMEOUT_SECONDS = 8.0


def plan_limit_http_json(
    url: str,
    *,
    headers: Mapping[str, str],
    data: bytes | None = None,
    method: str | None = None,
) -> dict[str, Any] | str:
    """Return the decoded JSON object, or a named reason for the failure."""
    request = urllib.request.Request(
        url, data=data, headers=dict(headers), method=method
    )
    try:
        with urllib.request.urlopen(
            request, timeout=PLAN_LIMIT_PROBE_TIMEOUT_SECONDS
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            return "stale_credential"
        return f"http_{exc.code}"
    except (OSError, json.JSONDecodeError, UnicodeDecodeError, TimeoutError) as exc:
        return f"http_read_failed_{type(exc).__name__}"
    return payload if isinstance(payload, dict) else "http_body_not_an_object"


__all__ = ["PLAN_LIMIT_PROBE_TIMEOUT_SECONDS", "plan_limit_http_json"]
