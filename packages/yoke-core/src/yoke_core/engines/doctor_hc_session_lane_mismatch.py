"""HC-session-lane-mismatch — detect divergent envelope vs row lanes.

The failure mode left a session whose top-level
``harness_sessions.execution_lane`` said ``DARIUS`` while its
persisted ``offer_envelope.execution_lane`` said ``primary``. The
server consulted the envelope and routed work the lane was never
authorised for. This HC reads every live session (``ended_at IS
NULL``) and flags rows where the persisted envelope's
``execution_lane`` differs from the row's authoritative
``execution_lane``. After the fix the envelope is written
from the row value, so any divergence here is either a regression of
the row-anchor path or a leftover from a session created before this
fix landed.

Registered in :mod:`yoke_core.engines.doctor_registry` so
``python3 -m yoke_core.engines.doctor`` runs it alongside the other
health checks.
"""

from __future__ import annotations

import json
from typing import Any, List, Optional, Tuple

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _get_columns as _schema_get_columns
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector

HC_SLUG = "HC-session-lane-mismatch"
HC_LABEL = "Session offer lane mismatch (envelope vs row)"


def _envelope_lane(blob: Optional[str]) -> Optional[str]:
    """Return ``execution_lane`` from a serialized offer envelope or ``None``."""
    if not blob:
        return None
    try:
        parsed = json.loads(blob)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    value = parsed.get("execution_lane")
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return str(value)


def _harness_sessions_has_columns(conn: Any) -> bool:
    """Return ``True`` when the schema exposes both lane columns."""
    try:
        names = set(_schema_get_columns(conn, "harness_sessions"))
    except Exception:
        return False
    return {"execution_lane", "offer_envelope", "ended_at"}.issubset(names)


def _scan_for_mismatches(conn: Any) -> List[Tuple[Any, ...]]:
    """Return ``(session_id, row_lane, envelope_lane)`` rows for live mismatches."""
    cursor = conn.execute(
        "SELECT session_id, execution_lane, offer_envelope "
        "FROM harness_sessions WHERE ended_at IS NULL"
    )
    findings: List[Tuple[Any, ...]] = []
    for session_id, row_lane, envelope_blob in cursor:
        envelope_lane = _envelope_lane(envelope_blob)
        if envelope_lane is None:
            continue
        row_lane_clean = (row_lane or "").strip()
        if not row_lane_clean:
            continue
        if envelope_lane != row_lane_clean:
            findings.append((session_id, row_lane_clean, envelope_lane))
    return findings


def hc_session_lane_mismatch(
    conn: Any,
    args: DoctorArgs,
    rec: RecordCollector,
) -> None:
    """Flag live sessions whose persisted offer envelope disagrees with the row.

    PASS when no live session is in disagreement, when the schema does
    not yet expose ``execution_lane`` / ``offer_envelope`` (cold-start
    or pre-cutover fixture), or when no live sessions exist.

    WARN listing each offending session when at least one mismatch is
    present. WARN rather than FAIL because the divergence is a
    routing-correctness alarm that operators should investigate, not
    a structural invariant violation that must hard-block other
    checks.
    """
    if not _harness_sessions_has_columns(conn):
        rec.record(HC_SLUG, HC_LABEL, "PASS", "")
        return

    try:
        findings = _scan_for_mismatches(conn)
    except db_backend.database_error_types(conn) as exc:
        rec.record(HC_SLUG, HC_LABEL, "WARN", f"query failed: {exc}")
        return

    if not findings:
        rec.record(HC_SLUG, HC_LABEL, "PASS", "")
        return

    detail_lines = [
        f"- {session_id}: row_lane='{row_lane}' envelope_lane='{env_lane}'"
        for session_id, row_lane, env_lane in findings
    ]
    rec.record(
        HC_SLUG,
        HC_LABEL,
        "WARN",
        "\n".join(detail_lines)
        + "\n(Investigate routing for these sessions; the row value is "
        "authoritative.)",
    )


__all__ = [
    "HC_LABEL",
    "HC_SLUG",
    "hc_session_lane_mismatch",
]
