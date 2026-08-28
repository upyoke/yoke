"""Who drove a session reactivation: the facts, and where they are recorded.

A reactivation is a process reviving a row it did not create, so "which
process revived session X, and what hook event drove it" is only answerable
if the reviving side says so at the moment it revives. The stamp built here
is that answer. It is recorded twice, from one dict, so the two records
agree: on the reactivation's own ``HarnessSessionStarted`` context — which
always exists — and, where the wake machinery has an attempt in flight, on
that attempt's evidence row.

The event-context record is the authority. Stamping only the wake attempt
is what left a reactivation with no attempt in flight recorded nowhere at
all: the earlier code returned as soon as the attempt row was missing,
which is precisely the case that had nothing else to fall back on.
"""

from __future__ import annotations

from typing import Any, Optional


def build_reactivation_driver_stamp(
    *,
    driver_surface: Optional[str],
    driver_version: Optional[str],
    driver: Optional[dict] = None,
) -> dict:
    """Return the driver facts a reactivation records about itself.

    This is the reactivation's OWN record, independent of whether a wake
    attempt is in flight. The wake-attempt evidence row is stamped from this
    same dict, so where both exist they carry identical values instead of two
    independently derived answers.
    """
    stamp: dict = {}
    surface = (driver_surface or "").strip() or None
    version = (driver_version or "").strip() or None
    if surface:
        stamp["driver_surface"] = surface
    if version:
        stamp["driver_version"] = version
    if isinstance(driver, dict):
        pid = driver.get("pid")
        ppid = driver.get("ppid")
        hook_event = driver.get("hook_event")
        origin = driver.get("origin")
        if isinstance(pid, int) and pid > 0:
            stamp["driver_pid"] = pid
        if isinstance(ppid, int) and ppid > 0:
            stamp["driver_ppid"] = ppid
        if isinstance(hook_event, str) and hook_event.strip():
            stamp["driver_hook_event"] = hook_event.strip()
        if isinstance(origin, str) and origin.strip():
            stamp["driver_pid_origin"] = origin.strip()
    return stamp


def record_reactivation_wake_driver(
    conn: Any,
    *,
    session_id: str,
    driver_surface: Optional[str],
    driver_version: Optional[str],
    driver: Optional[dict] = None,
) -> None:
    """Stamp the re-registering process on the open wake attempt, if any.

    The reactivation's own record is the ``HarnessSessionStarted`` context
    (see :func:`build_reactivation_driver_stamp`); this row is the wake
    machinery's copy, written only where an attempt is actually in flight.
    """
    stamp = build_reactivation_driver_stamp(
        driver_surface=driver_surface,
        driver_version=driver_version,
        driver=driver,
    )
    if not stamp:
        return
    from yoke_contracts.session_control.evidence import redacted_evidence_document
    from yoke_core.domain import db_backend, json_helper

    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    try:
        row = conn.execute(
            "SELECT attempt_id, evidence FROM session_message_attempts "
            f"WHERE target_session_id = {marker} "
            "AND attempt_kind IN ('wake_relay','wake_broker') "
            "AND completed_at IS NULL "
            "ORDER BY started_at DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        if row is None:
            return
        try:
            stored = json_helper.loads_text(str(row["evidence"] or "{}"))
        except (TypeError, ValueError):
            stored = {}
        payload = dict(stored) if isinstance(stored, dict) else {}
        payload.update(stamp)
        conn.execute(
            f"UPDATE session_message_attempts SET evidence = {marker} "
            f"WHERE attempt_id = {marker}",
            (
                json_helper.dumps_compact(redacted_evidence_document(payload)),
                row["attempt_id"],
            ),
        )
        conn.commit()
    except db_backend.operational_error_types(conn):
        try:
            conn.rollback()
        except Exception:
            pass


__all__ = [
    "build_reactivation_driver_stamp",
    "record_reactivation_wake_driver",
]
