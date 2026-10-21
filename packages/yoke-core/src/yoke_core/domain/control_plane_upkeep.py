"""Control-plane upkeep: GitHub observation and owed QA settlement replays.

Merge-queue landings and session CI waits settle only when someone reads
GitHub, and a QA waiver leaves its close-out replays owed in
``qa_settlement_followups``. :func:`run_control_plane_upkeep` does both once.
It rides scheduled work that already runs in the one long-lived process each
install mode has: the API server's health refresh (hosted and self-hosted),
or each cycle of a machine-local universe's standing relay, which dispatches
in-process and has no server. It starts no thread of its own.

The landing cadence row and each CI wait's read stamp hold GitHub reads to
the shared poll floor however often upkeep runs, and a settlement row is
claimed before its replay, so concurrent processes never repeat work. A
failed step is logged and the next run re-derives the same work from the
same durable rows. The landing observer records its failure on the project's
refresh row, where ``landing.observe`` reports it to a waiter; a replay that
raises keeps its error on its follow-up row, which the steering report lists.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from yoke_contracts.timestamps import utc_now
from yoke_core.domain.merge_queue_landing_observer import observe_pending_landings
from yoke_core.domain.project_identity import row_value
from yoke_core.domain.qa_settlement_followups import replay_settlement_followups
from yoke_core.domain.session_ci_wait_observer import observe_pending_ci_runs


_LOG = logging.getLogger(__name__)


def observe_pending_github_work(
    conn: Any, *, now: datetime | None = None
) -> dict[str, Any]:
    """Run both GitHub observers over every project; one failing spares the other."""
    current = utc_now() if now is None else now
    rows = conn.execute("SELECT id FROM projects ORDER BY id").fetchall()
    conn.commit()
    projects = [int(row_value(row, "id", 0)) for row in rows]
    result: dict[str, Any] = {"projects": len(projects)}
    try:
        landings = observe_pending_landings(conn, projects, now=current)
    except Exception as exc:  # noqa: BLE001 - the refresh row records it too
        conn.rollback()
        _LOG.warning("pending landing observation failed: %s", exc)
        landings = {"error": str(exc)}
    for notice in landings.get("notice_errors") or ():
        _LOG.warning("pending landing notice failed: %s", notice)
    result["landings"] = landings
    try:
        ci_runs = observe_pending_ci_runs(conn, projects, now=current)
    except Exception as exc:  # noqa: BLE001 - the next cycle reads it again
        conn.rollback()
        _LOG.warning("pending CI run observation failed: %s", exc)
        ci_runs = {"errors": [str(exc)]}
    else:
        for error in ci_runs.get("errors") or ():
            _LOG.warning("pending CI run observation failed: %s", error)
    result["ci_runs"] = ci_runs
    return result


def run_control_plane_upkeep() -> None:
    """Run each upkeep step once on a fresh connection; never raises.

    Its hosts keep standing whatever happens here, and a failed step spares
    the next one.
    """
    from yoke_core.domain.db_helpers import connect

    try:
        conn = connect()
    except Exception:  # noqa: BLE001 - the next run connects again
        _LOG.warning("control-plane upkeep could not connect", exc_info=True)
        return
    try:
        for name, step in (
            ("pending GitHub observation", observe_pending_github_work),
            ("QA settlement follow-up replay", replay_settlement_followups),
        ):
            try:
                step(conn)
            except Exception:  # noqa: BLE001 - its durable rows carry it over
                _LOG.warning("%s failed", name, exc_info=True)
                try:
                    conn.rollback()
                except Exception:  # noqa: BLE001 - the warning above is the report
                    pass
    finally:
        conn.close()


__all__ = ["observe_pending_github_work", "run_control_plane_upkeep"]
