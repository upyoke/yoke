"""HC-reflection-capture-hook-coverage — the Agent-tool capture path is wired.

For every ``HarnessToolCallCompleted`` event with ``tool_name='Agent'`` in the
last 24h, assert a matching ``ReflectionCaptureHookFired`` event with the same
``tool_use_id``. The subject is this project's own PostToolUse hook wiring, so
the check belongs to the project rather than to the universal engine roster.

The event-shape helpers are shared with the sibling
``HC-reflection-capture-unhandled`` check and are imported from its engine
module so both read the ledger the same way.

Self-skips cleanly on minimal-schema fixtures (missing ``events`` table,
missing columns) so it degrades to PASS in test/empty-history contexts
instead of FAIL.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.engines.doctor_hc_reflection_capture_hook_coverage import (
    _cutoff_24h,
    _events_table_present,
    _extract_tool_use_id,
    _p,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


_HC_COVERAGE_NAME = "HC-reflection-capture-hook-coverage"
_HC_COVERAGE_DESC = (
    "Every Agent-tool call in the last 24h emits a matching "
    "ReflectionCaptureHookFired event"
)


def _tool_use_ids_24h(conn: Any, event_predicate: str) -> set[str]:
    """Tool-use ids on events in the last 24h matching ``event_predicate``."""
    try:
        p = _p(conn)
        rows = conn.execute(
            f"SELECT payload FROM events WHERE {event_predicate} "
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
    """Every Agent-tool call in 24h emits ReflectionCaptureHookFired."""
    if not _events_table_present(conn):
        rec.record(
            _HC_COVERAGE_NAME, _HC_COVERAGE_DESC, "PASS",
            "events table not present (fixture/minimal-schema context); skipping",
        )
        return

    agent_calls = _tool_use_ids_24h(
        conn, "event_name='HarnessToolCallCompleted' AND tool_name='Agent'"
    )
    if not agent_calls:
        rec.record(
            _HC_COVERAGE_NAME, _HC_COVERAGE_DESC, "PASS",
            "no Agent-tool calls observed in the last 24h",
        )
        return

    fired = _tool_use_ids_24h(conn, "event_name='ReflectionCaptureHookFired'")
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


__all__ = ["hc_reflection_capture_hook_coverage"]

# Slug and display name are the ones this check has always reported under.
from yoke_project_checks._declare import (  # noqa: E402
    self_project_checks,
)

PROJECT_HEALTH_CHECKS = self_project_checks(
    ('reflection-capture-hook-coverage', 'Every Agent-tool call in 24h emits ReflectionCaptureHookFired', hc_reflection_capture_hook_coverage),
)
