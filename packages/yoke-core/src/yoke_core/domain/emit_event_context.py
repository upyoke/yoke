"""Context-payload helpers for the emit_event CLI surface.

Centralises the byte-budget constants, integer normalisation, and
context/error JSON payload parsing used by the orchestrator in
:mod:`yoke_core.domain.emit_event`. The orchestrator and tests depend on
the precise return shape of :func:`_parse_context_payload`:

* ``None`` when ``raw`` is empty/missing.
* The parsed JSON value (dict/list/scalar) when it parses and fits within
  ``MAX_CONTEXT_BYTES``.
* A truncation-marker dict when the parsed payload exceeds the byte budget.
* An ``_invalid_json`` marker dict when JSON parsing fails.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional


MAX_ENVELOPE_BYTES = 65536
MAX_CONTEXT_BYTES = 2048
MAX_STACKTRACE_BYTES = 4096

VALID_ERROR_CATEGORIES = {
    "agent_failure",
    "hook_failure",
    "db",
    "git",
    "dispatch",
    "validation",
    "external",
    "unknown",
}


def _truncate_bytes(value: str, limit: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= limit:
        return value
    return encoded[:limit].decode("utf-8", "ignore")


def _normalize_int(value: Optional[int]) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(str(value), 10)
    except ValueError:
        return None


def _validate_error_context(raw: Optional[str]) -> None:
    if not raw:
        return
    match = re.search(r'"error_category"\s*:\s*"([^"]+)"', raw)
    if not match:
        return
    category = match.group(1)
    if category not in VALID_ERROR_CATEGORIES:
        allowed = " ".join(sorted(VALID_ERROR_CATEGORIES))
        raise ValueError(
            f"invalid error_category '{category}'. Must be one of: {allowed}"
        )


def _parse_context_payload(raw: Optional[str], *, label: str) -> Any:
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {
            "_invalid_json": True,
            "_source": label,
            "_error": str(exc),
            "_raw": _truncate_bytes(raw, MAX_CONTEXT_BYTES),
        }
    if isinstance(payload, dict):
        stacktrace = payload.get("stacktrace")
        if isinstance(stacktrace, str):
            payload["stacktrace"] = _truncate_bytes(stacktrace, MAX_STACKTRACE_BYTES)
    encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(encoded) <= MAX_CONTEXT_BYTES:
        return payload
    if isinstance(payload, dict):
        shrunk: dict[str, Any] = {}
        for key in (
            "error_category",
            "error_message",
            "message",
            "reason",
            "hook",
            "check_id",
            "final_status",
            "dispatch_type",
            "tool_name",
            "command",
            "file_path",
            "response_preview",
            "attribution_source",
        ):
            if key in payload:
                value = payload[key]
                if isinstance(value, str):
                    value = _truncate_bytes(value, 512)
                shrunk[key] = value
        shrunk["_truncated"] = True
        encoded = json.dumps(shrunk, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        if len(encoded) <= MAX_CONTEXT_BYTES:
            return shrunk
    return {"_truncated": True}
