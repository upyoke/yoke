"""The control-plane reader that wakes a worker its CI run outlived.

A session dispatches a CI run through a watcher, ends its turn, and the
watcher dies with it. Nothing in that process survives to read the
conclusion, so the verdict the session stopped for reaches it only if
something on the control-plane side goes and gets it. That is this sweep:
relay upkeep calls it on every poll, it reads each pending wait's run, and
a concluded run becomes one message carrying the verdict
(:mod:`yoke_core.domain.session_ci_wait_notice`).

Three rules keep the sweep cheap and quiet. A session whose turn is still
in flight is skipped before any GitHub call, because it is reading that run
itself and a wake would interrupt the thing it is waiting on. A run whose
conclusion is already recorded is never read again — only its notice is
retried. And no single run is read more often than the shared GitHub poll
floor, so a fast relay cadence cannot turn a handful of waits into a
rate-limit budget.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Callable, Iterable

from yoke_core.domain import db_backend
from yoke_core.domain.github_poll_schedule import MINIMUM_POLL_INTERVAL_SECONDS
from yoke_core.domain.session_ci_wait_notice import (
    ci_run_message,
    notice_idempotency_key,
    push_ci_run_notice,
)
from yoke_core.domain.session_message_types import row_dict, timestamp, utc_now
from yoke_core.domain.session_reclaim_progress import session_turn_is_running


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def read_run_conclusion(project: str, repo: str, run_id: str) -> tuple[str, str, str]:
    """Ask GitHub for one run's status; return ``(status, conclusion, error)``.

    The App credentials live where the control plane runs, which is the
    same place this sweep runs, so the read needs no client involvement.
    """
    from yoke_contracts.github_app_installation_permissions import (
        GITHUB_ACTIONS_READ_PERMISSION_LEVELS,
    )
    from yoke_core.domain.gh_rest_transport import RestTransportError
    from yoke_core.domain.github_actions_rest import rest_get
    from yoke_core.domain.project_github_auth import resolve_project_github_auth

    try:
        auth = resolve_project_github_auth(
            project,
            required_permissions=GITHUB_ACTIONS_READ_PERMISSION_LEVELS,
        )
        data = rest_get(f"/repos/{repo}/actions/runs/{run_id}", token=auth.token)
    except RestTransportError as exc:
        return "", "", f"github run read failure: {exc}"
    except Exception as exc:  # noqa: BLE001 - auth refusals are evidence too
        return "", "", f"github run read unavailable: {exc}"
    if not isinstance(data, dict):
        return "", "", f"run {run_id} was not found in {repo}"
    return (
        str(data.get("status") or "").strip(),
        str(data.get("conclusion") or "").strip(),
        "",
    )


def _pending_rows(
    conn: Any, project_ids: Iterable[int], *, cutoff: str
) -> list[dict[str, Any]]:
    """Every wait that could still be answered, newest read last.

    Terminated sessions are excluded by the join rather than swept and
    skipped: a wait nobody can be woken for is inert, not pending work, and
    leaving it out of the candidate set is what bounds this table's cost
    without an expiry sweep of its own.
    """
    projects = tuple(sorted({int(value) for value in project_ids}))
    if not projects:
        return []
    marker = _p(conn)
    slots = ",".join(marker for _ in projects)
    rows = conn.execute(
        "SELECT w.id, w.session_id, w.project_id, w.repo, w.run_id, w.head_sha, "
        "w.kind, w.continue_command, w.conclusion, hs.actor_id, hs.turn_posture, "
        "p.slug "
        "FROM session_ci_run_waits w "
        "JOIN harness_sessions hs ON hs.session_id=w.session_id "
        "JOIN projects p ON p.id=w.project_id "
        f"WHERE w.project_id IN ({slots}) AND w.notified_at IS NULL "
        "AND hs.terminated_at IS NULL AND hs.actor_id IS NOT NULL "
        f"AND (w.conclusion<>'' OR w.read_at IS NULL OR w.read_at<={marker}) "
        "ORDER BY w.id",
        (*projects, cutoff),
    ).fetchall()
    return [row_dict(row) for row in rows]


def observe_pending_ci_runs(
    conn: Any,
    project_ids: Iterable[int],
    *,
    now: datetime | None = None,
    read_run: Callable[[str, str, str], tuple[str, str, str]] = read_run_conclusion,
    poll_floor_seconds: float = MINIMUM_POLL_INTERVAL_SECONDS,
) -> dict[str, Any]:
    """Read every due pending run and notify the sessions whose runs are over."""
    current = now or utc_now()
    current_text = timestamp(current)
    cutoff = timestamp(current - timedelta(seconds=float(poll_floor_seconds)))
    marker = _p(conn)
    result: dict[str, Any] = {
        "checked": 0,
        "in_flight_sessions": 0,
        "concluded": 0,
        "notified": 0,
        "errors": [],
    }
    try:
        rows = _pending_rows(conn, project_ids, cutoff=cutoff)
        conn.commit()
    except Exception as exc:
        conn.rollback()
        result["errors"].append(f"pending ci waits unreadable: {exc}")
        return result
    result["checked"] = len(rows)
    for row in rows:
        wait_id = int(row["id"])
        session_id = str(row["session_id"])
        if session_turn_is_running(row.get("turn_posture")):
            # The session is reading this run itself. Waking it would
            # interrupt the very wait the notice exists to end.
            result["in_flight_sessions"] += 1
            continue
        conclusion = str(row.get("conclusion") or "")
        try:
            if not conclusion:
                status, conclusion, error = read_run(
                    str(row["slug"]), str(row["repo"]), str(row["run_id"])
                )
                conn.execute(
                    f"UPDATE session_ci_run_waits SET read_at={marker} "
                    f"WHERE id={marker}",
                    (current_text, wait_id),
                )
                conn.commit()
                if error:
                    result["errors"].append(f"wait {wait_id}: {error}")
                    continue
                if status != "completed" or not conclusion:
                    continue
                conn.execute(
                    f"UPDATE session_ci_run_waits SET conclusion={marker} "
                    f"WHERE id={marker}",
                    (conclusion, wait_id),
                )
                conn.commit()
                result["concluded"] += 1
            delivery = push_ci_run_notice(
                conn,
                session_id=session_id,
                actor_id=int(row["actor_id"]),
                body=ci_run_message(
                    conclusion=conclusion,
                    repo=str(row["repo"]),
                    run_id=str(row["run_id"]),
                    head_sha=str(row.get("head_sha") or ""),
                    kind=str(row["kind"]),
                    continue_command=str(row.get("continue_command") or ""),
                ),
                idempotency_key=notice_idempotency_key(
                    session_id, str(row["run_id"])
                ),
                now=current,
            )
            if delivery == "delivered":
                # Acceptance ends the sweep's responsibility; the ordinary
                # pending-message path owns the rest of delivery.
                conn.execute(
                    f"UPDATE session_ci_run_waits SET notified_at={marker} "
                    f"WHERE id={marker} AND notified_at IS NULL",
                    (current_text, wait_id),
                )
                result["notified"] += 1
            conn.commit()
        except Exception as exc:  # noqa: BLE001 - one wait never poisons the sweep
            conn.rollback()
            result["errors"].append(f"wait {wait_id}: {exc}")
    return result


__all__ = ["observe_pending_ci_runs", "read_run_conclusion"]
