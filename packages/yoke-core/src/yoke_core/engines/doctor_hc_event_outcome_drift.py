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
import json
import re
from typing import Any, List, Tuple

from yoke_core.domain.runtime_settings import get_int, get_str
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector

HC_ID = "event-outcome-drift"
HC_NAME = "Historical event-outcome drift"
_TARGET_EVENT_NAME = "HarnessToolCallCompleted"
_TARGET_EVENT_OUTCOME = "completed"
_CUTOVER_CONFIG_KEY = "event_outcome_drift_cutover_at"
_TOLERANCE_CONFIG_KEY = "event_outcome_drift_pre_cutover_warn_max"
_DEFAULT_TOLERANCE = 10000
_EXIT_RE = re.compile(r"Exit code (\d+)")


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


def _has_drift_shape(envelope_text: Optional[str], exit_code: Optional[int]) -> bool:
    """A row has the drift shape when its exit_code is positive OR the
    envelope carries a non-empty top-level error / preview-nonzero-exit
    signal that the historical false-success bug used to hide."""
    if exit_code is not None and exit_code > 0:
        return True
    if not envelope_text:
        return False
    try:
        env = json.loads(envelope_text)
    except (TypeError, ValueError):
        return False
    if not isinstance(env, dict):
        return False
    detail = (env.get("context") or {}).get("detail") or {}
    error = detail.get("error")
    if isinstance(error, str) and error.strip():
        return True
    preview = detail.get("tool_response_preview")
    if isinstance(preview, str):
        m = _EXIT_RE.search(preview)
        if m and int(m.group(1)) > 0:
            return True
    return False


def _partition_drift_rows(
    conn: Any, cutover_at: str
) -> Tuple[List[Tuple[str, str]], int]:
    """Return (post_cutover_failures, pre_cutover_residual_count).

    post_cutover_failures: list of (event_id, created_at) for rows
    after the marker that still show the drift shape (regression).
    pre_cutover_residual_count: bare count of rows before the marker
    that the conservative backfill could not reclassify.
    """
    p = _p(conn)
    cursor = conn.execute(
        "SELECT event_id, created_at, envelope, exit_code FROM events "
        f"WHERE event_name = {p} AND event_outcome = {p}",
        (_TARGET_EVENT_NAME, _TARGET_EVENT_OUTCOME),
    )
    post: List[Tuple[str, str]] = []
    pre_residual = 0
    for event_id, created_at, envelope_text, exit_code in cursor.fetchall():
        if not _has_drift_shape(envelope_text, exit_code):
            continue
        if created_at and created_at > cutover_at:
            post.append((event_id, created_at))
        else:
            pre_residual += 1
    return post, pre_residual


def hc_event_outcome_drift(
    conn: Any, args: DoctorArgs, rec: RecordCollector
) -> None:
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
        post_failures, pre_residual = _partition_drift_rows(conn, cutover_at)
    except db_backend.database_error_types(conn) as exc:
        rec.record(
            f"HC-{HC_ID}",
            HC_NAME,
            "SKIP",
            f"events read failed: {exc}",
        )
        return

    if post_failures:
        sample = post_failures[:5]
        lines = [
            f"{len(post_failures)} post-cutover row(s) (after "
            f"{cutover_at}) still record event_outcome='completed' "
            "despite drift-shape evidence — regression in the live "
            "emitters. Sample:",
        ]
        for event_id, created_at in sample:
            lines.append(f"- event_id={event_id} created_at={created_at}")
        if len(post_failures) > len(sample):
            lines.append(f"- ... +{len(post_failures) - len(sample)} more")
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
