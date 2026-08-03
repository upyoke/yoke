"""HC-reflection-capture-unhandled — unrecognized reflection block shapes.

Queries the events table for ``ReflectionCaptureHookUnhandled`` events in the
last 24h and surfaces them as WARN, giving operators a one-stop view of
reflection shapes the parser can be extended to cover.

The event-shape helpers below (``_p``, ``_events_table_present``,
``_extract_tool_use_id``, ``_cutoff_24h``) are also consumed by the
project-local ``HC-reflection-capture-hook-coverage`` check so both read the
ledger the same way.

The check self-skips cleanly on minimal-schema fixtures (missing ``events``
table, missing columns) so it degrades to PASS in test/empty-history contexts
instead of FAIL.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _table_exists
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


_HC_UNHANDLED_NAME = "HC-reflection-capture-unhandled"
_HC_UNHANDLED_DESC = (
    "ReflectionCaptureHookUnhandled events in the last 24h "
    "(operator should extend the parser or false-positive registry)"
)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _events_table_present(conn: Any) -> bool:
    try:
        return _table_exists(conn, "events")
    except Exception:
        return False


def _extract_tool_use_id(payload_text: Any) -> str | None:
    if not payload_text:
        return None
    try:
        if isinstance(payload_text, (bytes, bytearray)):
            payload_text = payload_text.decode("utf-8", errors="ignore")
        if isinstance(payload_text, str):
            parsed = json.loads(payload_text)
        elif isinstance(payload_text, dict):
            parsed = payload_text
        else:
            return None
    except Exception:
        return None
    if not isinstance(parsed, dict):
        return None
    for key in ("tool_use_id", "tool_use", "tool_call_id"):
        value = parsed.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _cutoff_24h() -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=24)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _unhandled_excerpts_24h(conn: Any) -> list[dict]:
    try:
        p = _p(conn)
        rows = conn.execute(
            "SELECT payload, created_at FROM events "
            "WHERE event_name='ReflectionCaptureHookUnhandled' "
            f"AND created_at >= {p} "
            "ORDER BY created_at DESC",
            (_cutoff_24h(),),
        ).fetchall()
    except db_backend.database_error_types(conn):
        return []
    out: list[dict] = []
    for row in rows:
        payload_text, created_at = row[0], row[1]
        if not payload_text:
            continue
        try:
            parsed = (json.loads(payload_text)
                      if isinstance(payload_text, str) else payload_text)
        except Exception:
            continue
        if not isinstance(parsed, dict):
            continue
        out.append({
            "created_at": created_at,
            "tool_use_id": parsed.get("tool_use_id"),
            "role": parsed.get("role"),
            "blocks_unrecognized": parsed.get("blocks_unrecognized"),
            "examples": parsed.get("raw_examples") or [],
        })
    return out


def hc_reflection_capture_unhandled(
    conn: Any, args: DoctorArgs, rec: RecordCollector,
) -> None:
    if not _events_table_present(conn):
        rec.record(
            _HC_UNHANDLED_NAME, _HC_UNHANDLED_DESC, "PASS",
            "events table not present (fixture/minimal-schema context); skipping",
        )
        return

    entries = _unhandled_excerpts_24h(conn)
    if not entries:
        rec.record(
            _HC_UNHANDLED_NAME, _HC_UNHANDLED_DESC, "PASS",
            "no ReflectionCaptureHookUnhandled events in the last 24h",
        )
        return

    detail_lines = [
        f"{len(entries)} ReflectionCaptureHookUnhandled event(s) "
        "in the last 24h. Each names a reflection-bounded block "
        "whose shape did not match any known parser:",
    ]
    for entry in entries[:10]:
        excerpt = ""
        if entry["examples"]:
            first = entry["examples"][0]
            if isinstance(first, dict):
                excerpt = (first.get("excerpt") or "")[:160]
        detail_lines.append(
            f"- {entry['created_at']} role={entry['role']} "
            f"blocks_unrecognized={entry['blocks_unrecognized']} "
            f"excerpt={excerpt!r}",
        )
    if len(entries) > 10:
        detail_lines.append(f"... ({len(entries) - 10} more)")
    detail_lines.append(
        "Remediation: extend "
        "yoke_core.domain.reflection_capture_shape_parsers with a "
        "shape parser covering the observed block, OR confirm the "
        "shape is a one-off and add a false-positive classifier to "
        "yoke_core.domain.reflection_capture_shapes.",
    )
    rec.record(_HC_UNHANDLED_NAME, _HC_UNHANDLED_DESC, "WARN", "\n".join(detail_lines))


__all__ = ["hc_reflection_capture_unhandled"]
