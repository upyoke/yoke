"""Detect active harness sessions whose tool activity has no hook telemetry."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Sequence, Tuple

import yoke_core.engines.doctor_report as _base

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _column_exists, _table_exists
from yoke_core.domain.worktree_harness_enablement import (
    HookEnablementContribution,
    load_hook_enablement_contributions,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from yoke_project_checks._declare import self_project_checks


HC_SLUG = "HC-hooks-expected-but-silent"
HC_LABEL = "Harness hooks expected but silent"
_HOOK_TELEMETRY_EVENTS = (
    "HookDispatchTelemetry",
    "HookExecutionFailed",
    "HookGuardrailEvaluated",
)
_MAX_FINDINGS = 50


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _tool_activity_query(
    conn: Any,
    *,
    use_session_tool_calls: bool,
) -> Tuple[str, Sequence[Any]]:
    """Build a schema-tolerant query for active tool-producing sessions."""
    p = _placeholder(conn)
    event_args = tuple(_HOOK_TELEMETRY_EVENTS)
    event_placeholders = ", ".join(p for _ in event_args)
    if use_session_tool_calls:
        activity = (
            "EXISTS (SELECT 1 FROM session_tool_calls t "
            "WHERE t.session_id = s.session_id)"
        )
    else:
        activity = (
            "(COALESCE(s.tool_call_count, 0) > 0 "
            "OR s.last_tool_call_at IS NOT NULL)"
        )
    sql = (
        "SELECT s.session_id, s.executor "
        "FROM harness_sessions s "
        "WHERE s.ended_at IS NULL "
        f"AND {activity} "
        "AND NOT EXISTS ("
        "SELECT 1 FROM events e "
        "WHERE e.session_id = s.session_id "
        f"AND e.event_name IN ({event_placeholders})"
        ") "
        "ORDER BY s.session_id "
        f"LIMIT {_MAX_FINDINGS}"
    )
    return sql, event_args


def _active_silent_sessions(conn: Any) -> List[Tuple[str, str]] | None:
    """Return active sessions with tool activity but no hook dispatch event."""
    if not _table_exists(conn, "harness_sessions") or not _table_exists(conn, "events"):
        return None
    if not _column_exists(conn, "harness_sessions", "ended_at"):
        return None
    has_activity_columns = all(
        _column_exists(conn, "harness_sessions", column)
        for column in ("tool_call_count", "last_tool_call_at")
    )
    has_tool_call_rows = _table_exists(conn, "session_tool_calls")
    if not has_activity_columns and not has_tool_call_rows:
        return None
    query, params = _tool_activity_query(
        conn,
        use_session_tool_calls=not has_activity_columns,
    )
    return [
        (str(row[0]), str(row[1]))
        for row in conn.execute(query, params).fetchall()
    ]


def _expected_by_harness(repo_root: str) -> Dict[str, HookEnablementContribution]:
    return {
        contribution.harness_id: contribution
        for contribution in load_hook_enablement_contributions(repo_root)
    }


def hc_hooks_expected_but_silent(
    conn: Any,
    args: DoctorArgs,
    rec: RecordCollector,
) -> None:
    """Report harness-specific hook expectations that produce no telemetry."""
    repo_root = _base._resolve_repo_root()
    if not repo_root:
        rec.record(HC_SLUG, HC_LABEL, "SKIP", "could not resolve the repo root")
        return

    try:
        expected = _expected_by_harness(str(repo_root))
        sessions = _active_silent_sessions(conn)
    except db_backend.database_error_types(conn) as exc:
        rec.record(HC_SLUG, HC_LABEL, "SKIP", f"hook silence scan failed: {exc}")
        return

    if sessions is None:
        rec.record(
            HC_SLUG,
            HC_LABEL,
            "SKIP",
            "session/tool telemetry schema is not available on this DB",
        )
        return

    if not expected:
        rec.record(
            HC_SLUG,
            HC_LABEL,
            "PASS",
            "no manifest-declared harness hook expectations found",
        )
        return

    grouped: Dict[str, List[str]] = defaultdict(list)
    for session_id, executor in sessions:
        if executor in expected:
            grouped[executor].append(session_id)

    if not grouped:
        rec.record(
            HC_SLUG,
            HC_LABEL,
            "PASS",
            "active tool-producing sessions have hook dispatch telemetry for "
            + ", ".join(sorted(expected)),
        )
        return

    detail: List[str] = []
    for executor in sorted(grouped):
        contribution = expected[executor]
        affordances = ", ".join(contribution.affordances) or "native hook chain"
        session_ids = ", ".join(grouped[executor])
        detail.append(
            f"{executor}: hooks-expected-but-silent; sessions={session_ids}; "
            f"manifest expects {affordances}"
        )
    detail.append(
        "A session with tool activity and no hook telemetry is a lane "
        "delivery gap; repair the harness lane enablement before retrying."
    )
    rec.record(HC_SLUG, HC_LABEL, "WARN", "\n".join(detail))


PROJECT_HEALTH_CHECKS = self_project_checks(
    (
        "hooks-expected-but-silent",
        "Harness hooks expected but silent",
        hc_hooks_expected_but_silent,
    ),
)


__all__ = [
    "HC_LABEL",
    "HC_SLUG",
    "PROJECT_HEALTH_CHECKS",
    "hc_hooks_expected_but_silent",
]
