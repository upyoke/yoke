"""Who may take over a run that waits only on item QA on its target.

A takeover moves the older run's waiting members and may cancel it, so it
answers to whoever owns that run:

* **A live driver owns the run outright.** Only the driving session may take
  it over.
* **A live steering seat covering the project owns its releases.** Without a
  live driver, only the seat holder or the session that created the older run
  may take it over. Any other session reports its landing to steering, which
  batches releases; a driver that lapsed between ticks does not open the run
  to whichever session creates next.
* **No seat covers the project.** Any session that may create the run may
  take the older one over.

Every refusal happens inside the creation transaction, so nothing is created
or moved.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_contracts.refusal_recovery import compose_refusal

from yoke_core.domain.db_helpers import query_one, utc_now
from yoke_core.domain.deployment_run_insert import CREATOR_SESSION_COLUMN
from yoke_core.domain.schema_common import _column_exists

DRIVEN_ELSEWHERE_CODE = "takeover_run_driven_elsewhere"
RESERVED_FOR_STEERING_CODE = "takeover_reserved_for_steering"


def _creator_session(conn: Any, run_id: str) -> str:
    if not _column_exists(conn, "deployment_runs", CREATOR_SESSION_COLUMN):
        return ""
    row = query_one(
        conn,
        f"SELECT {CREATOR_SESSION_COLUMN} AS creator FROM deployment_runs WHERE id=%s",
        (run_id,),
    )
    return str(row["creator"] or "").strip() if row else ""


def require_takeover_authority(
    conn: Any, old_id: str, project_id: int, session_id: Optional[str]
) -> None:
    """Refuse unless *session_id* may take over run *old_id*."""
    from yoke_core.domain.deployment_run_driver_attachment import (
        format_refusal,
        live_attachment_for_run,
    )
    from yoke_core.domain.deployment_run_target_takeover import TakeoverRefused
    from yoke_core.domain.steering_scope_coverage import covering_seat

    caller = str(session_id or "").strip()
    driver = live_attachment_for_run(conn, run_id_value=old_id, now=utc_now())
    if driver is not None:
        if driver.session_id == caller:
            return
        raise TakeoverRefused(
            DRIVEN_ELSEWHERE_CODE,
            f"run {old_id} waits only on item QA on this target, but another "
            "session drives it, and a run with a live driver answers only to "
            "that session. Create this run from that session, or let its "
            "driver finish or stop first. " + format_refusal(old_id, driver),
        )
    seat = covering_seat(conn, {"project_id": int(project_id)})
    if seat is None:
        return
    holder = str(seat["session_id"])
    creator = _creator_session(conn, old_id)
    if caller and caller in {holder, creator}:
        return
    raise TakeoverRefused(
        RESERVED_FOR_STEERING_CODE,
        compose_refusal(
            f"run {old_id} waits only on item QA on this target, and steering session {holder} holds the live seat covering project {project_id}. Only that session or the session that created {old_id} ({creator or 'not recorded'}) may take it over, so nothing was created or changed.",
            recovery=(
                "report the landing to steering and wait; it batches releases: printf %s "
                '"LANDED <ref> <merge sha>" | yoke say --stdin --steering'
            ),
        ),
    )


__all__ = [
    "DRIVEN_ELSEWHERE_CODE",
    "RESERVED_FOR_STEERING_CODE",
    "require_takeover_authority",
]
