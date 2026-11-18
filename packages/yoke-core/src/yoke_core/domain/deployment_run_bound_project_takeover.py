"""Supersede another project's never-started run once a release ships past it.

A run that binds project P's source delivers P's merges. A ``created`` run of
P itself still holds custody of every P item it names, so a release carrying
a later P commit would exclude those items for as long as the stale run sat
unstarted, and same-project takeover never sees it. When this run's pinned
P commit contains the stale run's pin, on an environment of the same name,
the stale run is superseded exactly as a same-project takeover supersedes
one: its members and QA move here and it is cancelled, each removal and the
cancellation recording this run as the reason.

A stale run with a live driver answers only to that driver. It is left alone
and keeps its custody, so this run's custody reports it as the holder of
each item it names. A stale run whose pin this run does not contain keeps its
custody too: this run is not shipping that commit.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain.db_helpers import query_one, query_rows, utc_now

_COLUMNS = (
    "id,status,current_stage,settling_at,release_lineage,supersedes_run_id,created_at"
)


def _stale_runs(conn: Any, project_id: int, environment: str, run_id: str) -> list[dict]:
    """Project *project_id*'s pinned never-started runs on *environment*, oldest first."""
    from yoke_core.domain.deployment_run_member_targeting import run_environment_name

    rows = query_rows(
        conn,
        f"SELECT {_COLUMNS} FROM deployment_runs WHERE project_id=%s "
        "AND status='created' AND superseded_by_run_id IS NULL AND id<>%s "
        "AND COALESCE(release_lineage,'')<>'' ORDER BY created_at,id",
        (int(project_id), str(run_id)),
    )
    return [
        dict(row)
        for row in rows
        if run_environment_name(conn, str(row["id"])) == environment
    ]


def _driven_elsewhere(conn: Any, run_id: str, session_id: Optional[str]) -> bool:
    from yoke_core.domain.deployment_run_driver_attachment import (
        live_attachment_for_run,
    )

    driver = live_attachment_for_run(conn, run_id_value=run_id, now=utc_now())
    return driver is not None and driver.session_id != str(session_id or "").strip()


def supersede_stale_bound_project_runs(
    conn: Any,
    run_id: str,
    *,
    session_id: Optional[str] = None,
    actor_id: Optional[int] = None,
    apply: bool = True,
) -> tuple[str, ...]:
    """Supersede each bound project's never-started run this run ships past.

    Returns the superseded run ids. The caller owns the transaction and the
    QA ownership write scope, as for :func:`take_over_waiting_run`.
    """
    from yoke_core.domain.deployment_run_member_targeting import run_environment_name
    from yoke_core.domain.deployment_run_project_sources import (
        carried_project_ids,
        run_source_sha,
    )
    from yoke_core.domain.deployment_run_takeover_authority import (
        DRIVEN_ELSEWHERE_CODE,
    )
    from yoke_core.domain.deployment_run_target_takeover import (
        NOT_CONTAINED_CODE,
        TakeoverRefused,
        _supersede,
        takeover_available,
    )
    from yoke_core.domain.deployment_run_takeover_eligibility import _with_stages

    if not takeover_available(conn):
        return ()
    new_run = query_one(
        conn,
        "SELECT id,project_id,flow,target_environment_id,release_lineage "
        "FROM deployment_runs WHERE id=%s",
        (str(run_id),),
    )
    environment = run_environment_name(conn, str(run_id))
    if new_run is None or not environment:
        return ()
    superseded: list[str] = []
    for project_id in carried_project_ids(conn, str(run_id))[1:]:
        sha = run_source_sha(conn, str(run_id), int(project_id))
        if not sha:
            continue
        # Compared, and authorised, as project P's release on this commit.
        carrier = {**dict(new_run), "project_id": int(project_id), "release_lineage": sha}
        for stale in _stale_runs(conn, int(project_id), environment, str(run_id)):
            stale_id = str(stale["id"])
            if _driven_elsewhere(conn, stale_id, session_id):
                continue
            basis = (
                f"which ships project {project_id} at {sha}, containing this "
                "never-started run's candidate"
            )
            try:
                taken = _supersede(
                    conn,
                    carrier,
                    _with_stages(conn, stale),
                    session_id,
                    actor_id,
                    apply,
                    basis=basis,
                )
            except TakeoverRefused as refusal:
                # Refused before any write: the run keeps its custody, and
                # this run's custody names it as the holder.
                if refusal.code in {NOT_CONTAINED_CODE, DRIVEN_ELSEWHERE_CODE}:
                    continue
                raise
            if taken:
                superseded.append(stale_id)
    return tuple(superseded)


__all__ = ["supersede_stale_bound_project_runs"]
