"""Doctor HC for the historical event-outcome drift backfill.

Companion check for the one-shot ``backfill_event_outcomes`` audit
entry recorded during cutover. The HC reads the
``event_outcome_drift_cutover_at`` marker and partitions ``events`` rows with
``event_name='HarnessToolCallCompleted'`` AND ``event_outcome='completed'``
into a pre- and post-cutover bucket.

Outcomes:

* **FAIL** — any post-cutover row carries the drift shape (nonzero
  ``exit_code`` OR non-empty envelope ``error`` field). Real regressions
  in the live emitters from sibling tasks would surface here.
* **WARN** — only legacy pre-cutover rows remain (truncated envelopes,
  ambiguous previews, anything the conservative backfill skipped). The
  count is informational and bounded by the configurable tolerance
  ``event_outcome_drift_pre_cutover_warn_max`` (default 10000).
* **PASS** — no post-cutover drift AND pre-cutover residual is zero.
* **WARN** — the backfill audit row exists but the explicit cutover marker
  is missing, so the HC cannot distinguish pre-merge live-main rows from
  true post-cutover regressions.
* **SKIP** — backfill has not been applied yet (no cutover marker and no
  completed audit row). Reported as PASS with a "cutover-not-yet-applied"
  advisory so the HC does not noise pre-apply environments.
"""

from __future__ import annotations

from yoke_core.domain import db_backend
from typing import Any

from yoke_contracts.doctor_budget import CHECK_BUDGET_S, remaining_seconds

from yoke_core.domain.sql_json import jsonb_text_expr
from yoke_core.domain.runtime_settings import get_int, get_str
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector

HC_ID = "event-outcome-drift"
HC_NAME = "Historical event-outcome drift"
_TARGET_EVENT_NAME = "HarnessToolCallCompleted"
_TARGET_EVENT_OUTCOME = "completed"
_CUTOVER_CONFIG_KEY = "event_outcome_drift_cutover_at"
_TOLERANCE_CONFIG_KEY = "event_outcome_drift_pre_cutover_warn_max"
_DEFAULT_TOLERANCE = 10000
_LIST_PREVIEW = 5


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _resolve_cutover_marker() -> str:
    """Return the explicit cutover marker from machine config."""
    return get_str(_CUTOVER_CONFIG_KEY, "")


def _has_completed_backfill_audit(conn: Any) -> bool:
    """Return True once the backfill wrote a completed audit row."""
    p = _p(conn)
    try:
        row = conn.execute(
            "SELECT id FROM migration_audit "
            f"WHERE migration_name = {p} AND state = 'completed' "
            "ORDER BY id DESC LIMIT 1",
            ("backfill_event_outcomes",),
        ).fetchone()
    except db_backend.database_error_types(conn):
        return False
    return row is not None


def _partition_drift_rows(conn: Any, cutover_at: str) -> tuple[int, int, list]:
    """Count the entire ledger in SQL; return only a bounded failure preview."""
    sql = rf"""
        WITH candidates AS (
            SELECT event_id, created_at, exit_code,
                CASE WHEN envelope IS JSON OBJECT THEN {jsonb_text_expr("envelope")}
                     ELSE '{{}}'::jsonb END AS env
            FROM events WHERE event_name=%s AND event_outcome=%s
        ), drift AS (
            SELECT event_id, created_at FROM candidates
            WHERE exit_code > 0
                OR (jsonb_typeof(env #> '{{context,detail,error}}') = 'string'
                    AND (env #>> '{{context,detail,error}}') ~ '\S')
                OR (jsonb_typeof(env #> '{{context,detail,tool_response_preview}}') = 'string'
                    AND COALESCE(substring(env #>> '{{context,detail,tool_response_preview}}'
                        FROM 'Exit code ([0-9]+)'), '0') ~ '[1-9]')
        )
        SELECT COUNT(*) FILTER (WHERE created_at > %s),
               COUNT(*) FILTER (WHERE created_at <= %s OR created_at IS NULL),
               (SELECT COALESCE(json_agg(sample), '[]'::json) FROM (
                   SELECT event_id, created_at FROM drift WHERE created_at > %s
                   ORDER BY created_at, event_id LIMIT %s
               ) sample)
        FROM drift
    """
    remaining_seconds(CHECK_BUDGET_S)
    row = conn.execute(
        sql,
        (
            _TARGET_EVENT_NAME,
            _TARGET_EVENT_OUTCOME,
            cutover_at,
            cutover_at,
            cutover_at,
            _LIST_PREVIEW,
        ),
    ).fetchone()
    remaining_seconds(CHECK_BUDGET_S)
    return int(row[0]), int(row[1]), row[2]


def hc_event_outcome_drift(conn: Any, args: DoctorArgs, rec: RecordCollector) -> None:
    cutover_at = _resolve_cutover_marker()
    if not cutover_at:
        if _has_completed_backfill_audit(conn):
            rec.record(
                f"HC-{HC_ID}",
                HC_NAME,
                "WARN",
                "cutover-marker-missing: completed backfill_event_outcomes "
                "audit row exists, but machine config has no "
                f"{_CUTOVER_CONFIG_KEY} marker. HC cannot enforce "
                "post-cutover drift until the explicit marker lands.",
            )
            return
        rec.record(
            f"HC-{HC_ID}",
            HC_NAME,
            "PASS",
            "cutover-not-yet-applied: backfill_event_outcomes has not "
            "been applied to this DB; HC defers until the cutover marker "
            "lands.",
        )
        return

    tolerance = get_int(_TOLERANCE_CONFIG_KEY, _DEFAULT_TOLERANCE)

    try:
        post_count, pre_residual, sample = _partition_drift_rows(conn, cutover_at)
    except db_backend.database_error_types(conn) as exc:
        rec.record(
            f"HC-{HC_ID}",
            HC_NAME,
            "SKIP",
            f"events read failed: {exc}",
        )
        return

    if post_count:
        lines = [
            f"{post_count} post-cutover row(s) (after "
            f"{cutover_at}) still record event_outcome='completed' "
            "despite drift-shape evidence — regression in the live "
            "emitters. Sample:",
        ]
        for row in sample:
            lines.append(f"- event_id={row['event_id']} created_at={row['created_at']}")
        if post_count > len(sample):
            lines.append(f"- ... +{post_count - len(sample)} more")
        rec.record(f"HC-{HC_ID}", HC_NAME, "FAIL", "\n".join(lines))
        return

    if pre_residual > 0:
        verdict = "WARN" if pre_residual <= tolerance else "FAIL"
        detail = (
            f"{pre_residual} legacy pre-cutover row(s) with drift shape "
            "remain (truncated envelopes / ambiguous previews the "
            f"backfill conservatively left alone; tolerance={tolerance})."
        )
        if verdict == "FAIL":
            detail += (
                " Residual exceeds tolerance — investigate or raise "
                f"{_TOLERANCE_CONFIG_KEY} in machine config."
            )
        rec.record(f"HC-{HC_ID}", HC_NAME, verdict, detail)
        return

    rec.record(
        f"HC-{HC_ID}",
        HC_NAME,
        "PASS",
        f"No post-cutover drift; no pre-cutover residual (cutover={cutover_at}).",
    )


__all__ = ["HC_ID", "HC_NAME", "hc_event_outcome_drift"]
