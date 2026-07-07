"""HC-reflection-capture-hook-coverage and HC-reflection-capture-unhandled.

Two related doctor health checks for the PostToolUse Agent-tool
reflection-capture hook:

* ``HC-reflection-capture-hook-coverage`` — for every
  ``HarnessToolCallCompleted`` event with ``tool_name='Agent'`` in the
  last 24h, assert a matching ``ReflectionCaptureHookFired`` event with
  the same ``tool_use_id``. Catches future hook-deletion regressions and
  any wiring break that silently drops the capture path.
* ``HC-reflection-capture-unhandled`` — query the events table for
  ``ReflectionCaptureHookUnhandled`` events in the last 24h and surface
  them as WARN. Gives operators a one-stop view of unrecognized
  reflection shapes the parser can be extended to cover.

Both checks self-skip cleanly on minimal-schema fixtures (missing
``events`` table, missing columns) so they degrade to PASS in
test/empty-history contexts instead of FAIL.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _table_exists
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


_HC_COVERAGE_NAME = "HC-reflection-capture-hook-coverage"
_HC_COVERAGE_DESC = (
    "Every Agent-tool call in the last 24h emits a matching "
    "ReflectionCaptureHookFired event"
)
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


def _agent_tool_use_ids_24h(conn: Any) -> set[str]:
    try:
        p = _p(conn)
        rows = conn.execute(
            "SELECT payload FROM events "
            "WHERE event_name='HarnessToolCallCompleted' "
            "AND tool_name='Agent' "
            f"AND created_at >= {p}",
            (_cutoff_24h(),),
        ).fetchall()
    except db_backend.database_error_types(conn):
        return set()
    out: set[str] = set()
    for row in rows:
        ttid = _extract_tool_use_id(row[0])
        if ttid:
            out.add(ttid)
    return out


def _fired_tool_use_ids_24h(conn: Any) -> set[str]:
    try:
        p = _p(conn)
        rows = conn.execute(
            "SELECT payload FROM events "
            "WHERE event_name='ReflectionCaptureHookFired' "
            f"AND created_at >= {p}",
            (_cutoff_24h(),),
        ).fetchall()
    except db_backend.database_error_types(conn):
        return set()
    out: set[str] = set()
    for row in rows:
        ttid = _extract_tool_use_id(row[0])
        if ttid:
            out.add(ttid)
    return out


def hc_reflection_capture_hook_coverage(
    conn: Any, args: DoctorArgs, rec: RecordCollector,
) -> None:
    if not _events_table_present(conn):
        rec.record(
            _HC_COVERAGE_NAME, _HC_COVERAGE_DESC, "PASS",
            "events table not present (fixture/minimal-schema context); skipping",
        )
        return

    agent_calls = _agent_tool_use_ids_24h(conn)
    if not agent_calls:
        rec.record(
            _HC_COVERAGE_NAME, _HC_COVERAGE_DESC, "PASS",
            "no Agent-tool calls observed in the last 24h",
        )
        return

    fired = _fired_tool_use_ids_24h(conn)
    missing = sorted(agent_calls - fired)
    if not missing:
        rec.record(
            _HC_COVERAGE_NAME, _HC_COVERAGE_DESC, "PASS",
            f"all {len(agent_calls)} Agent-tool calls in the last 24h "
            "have matching ReflectionCaptureHookFired events",
        )
        return

    detail_lines = [
        f"{len(missing)}/{len(agent_calls)} Agent-tool calls in the last 24h "
        "lack a matching ReflectionCaptureHookFired event:",
    ]
    for tid in missing[:20]:
        detail_lines.append(f"- tool_use_id={tid}")
    if len(missing) > 20:
        detail_lines.append(f"... ({len(missing) - 20} more)")
    detail_lines.append(
        "Probable cause: PostToolUse Agent matcher not firing the "
        "reflection_capture_hook chain. Verify "
        "yoke_contracts.hook_runner.hook_ordering registers "
        "'Agent': _POST_AGENT under PostToolUse, then re-render "
        "settings.json via agents.render.run.",
    )
    rec.record(_HC_COVERAGE_NAME, _HC_COVERAGE_DESC, "FAIL", "\n".join(detail_lines))


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


__all__ = [
    "hc_reflection_capture_hook_coverage",
    "hc_reflection_capture_unhandled",
]
