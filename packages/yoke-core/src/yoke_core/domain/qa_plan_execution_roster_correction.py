"""Carry a corrected case into a live walk that has not reached it yet.

A live execution freezes its roster when it begins, and each entry is the
whole contract its case runs against. A plan refresh or an admitted-copy
correction rewrites requirement rows (a refresh that would add a case to a
live walk refuses instead, :func:`carry_into_live_rosters`); when one of those rows sits in a live
roster, the walk decides what the correction may do:

* An entry the walk has **not reached** -- after the cursor, with no result
  recorded ahead -- has judged nothing yet. It is rebuilt from the corrected
  row, and the roster digest moves with it, so the case runs as corrected and
  the cases already passed keep their results.
* An entry the walk **has reached** -- at or before the cursor, or recorded
  ahead -- holds evidence about the definition it ran. Changing it refuses
  with the exact abort command; after the abort the plan runs again on the
  corrected rows.

The walker learns of a corrected roster from the digest its next check-in
returns (:func:`yoke_core.domain.qa_plan_execution_checkin.stop_if_told`).
"""

from __future__ import annotations

import json
from typing import Any, Iterable

from yoke_core.domain.db_helpers import query_one, query_rows
from yoke_core.domain.qa_plan_execution_roster_change import abort_command
from yoke_core.domain.qa_plan_execution_schema import LIVE_PLAN_EXECUTION_SQL
from yoke_core.domain.qa_plan_execution_store import (
    canonical,
    lock_plan_execution,
    marker,
    result_rows,
    roster_digest,
)
from yoke_core.domain.schema_common import _table_exists

ROSTER_CASE_REACHED_CODE = "qa_roster_case_reached"

#: Entry keys the walking session resolves for itself (its source lane and
#: the run's source revision). They describe where a case runs, not what it
#: is, so they never make a reached case count as changed.
_SESSION_KEYS = frozenset(
    {
        "lane_id",
        "lane_branch",
        "lane_path",
        "lane_commit_sha",
        "deployment_source_revision",
    }
)


def _reached(execution: dict[str, Any], ordinal: int, recorded: set[int]) -> bool:
    return ordinal <= int(execution["cursor_ordinal"]) or ordinal in recorded


def _definition(entry: dict[str, Any]) -> str:
    return canonical({k: v for k, v in entry.items() if k not in _SESSION_KEYS})


def reached_by_live_execution(conn: Any, requirement_id: int) -> str | None:
    """The live execution whose walk has already reached this case, if any."""
    for execution, ordinals in _holders(conn, {int(requirement_id)}, lock=False):
        recorded = {row["ordinal"] for row in result_rows(conn, execution["id"])}
        if any(_reached(execution, ordinal, recorded) for ordinal, _ in ordinals):
            return str(execution["id"])
    return None


def _holders(
    conn: Any, requirement_ids: set[int], *, lock: bool
) -> list[tuple[dict[str, Any], list[tuple[int, dict[str, Any]]]]]:
    """Each live execution holding any of these rows, with the held entries.

    Rosters are read unlocked first; only an execution that holds one of
    these rows is locked (when ``lock``), so unrelated walks keep checking in.
    """
    if not requirement_ids or not _table_exists(conn, "qa_plan_executions"):
        return []
    found = []
    for row in query_rows(
        conn,
        "SELECT id,cursor_ordinal,roster_json FROM qa_plan_executions "
        f"WHERE state IN ({LIVE_PLAN_EXECUTION_SQL}) ORDER BY id",
        (),
    ):
        execution = {**dict(row), "roster": json.loads(str(row["roster_json"]))}
        if not any(
            int(entry.get("requirement_id") or 0) in requirement_ids
            for entry in execution["roster"]
        ):
            continue
        if lock:
            execution = lock_plan_execution(conn, str(row["id"]))
        held = [
            (ordinal, dict(entry))
            for ordinal, entry in enumerate(execution["roster"])
            if int(entry["requirement_id"]) in requirement_ids
        ]
        if held:
            found.append((execution, held))
    return found


def _rebuilt(conn: Any, execution: dict[str, Any], entry: dict[str, Any]) -> Any:
    """The entry ``begin`` would freeze for this row now, or ``None`` if retired."""
    from yoke_core.domain.qa_case_execution_context import (
        QaCaseExecutionError,
        execution_host_capability_kinds,
        get_case_execution_context,
    )
    from yoke_core.domain.qa_obligation_settlement import unanswered_attempt_sql

    requirement_id = int(entry["requirement_id"])
    owed = query_one(
        conn,
        f"SELECT 1 AS owed FROM qa_requirements WHERE id={marker(conn)} "
        f"AND waived_at IS NULL AND {unanswered_attempt_sql(conn)}",
        (requirement_id,),
    )
    if owed is None:
        return None
    session_id = str(execution["session_id"])
    try:
        context = get_case_execution_context(
            conn,
            requirement_id=requirement_id,
            host_capability_kinds=execution_host_capability_kinds(
                conn, session_id=session_id
            ),
            session_id=session_id,
            checkout_path=entry.get("lane_path"),
            expected_branch=entry.get("lane_branch"),
        )
    except QaCaseExecutionError as exc:
        from yoke_core.domain.qa_plan_management import QaPlanError

        raise QaPlanError(
            _refusal(
                conn,
                execution,
                int(entry["ordinal"]),
                f"can no longer be prepared for the walk ({exc})",
            )
        ) from exc
    return {
        **context,
        **{
            key: entry[key]
            for key in ("ordinal", "case_position", "baseline_position")
            if key in entry
        },
    }


def _refusal(conn: Any, execution: dict[str, Any], ordinal: int, what: str) -> str:
    entry = execution["roster"][ordinal]
    return (
        f"{ROSTER_CASE_REACHED_CODE}: requirement {entry['requirement_id']} at "
        f"roster position {ordinal} of live QA execution {execution['id']} "
        f"{what}. Abort the execution with `{abort_command(conn, execution)}`, "
        "re-apply the correction, then run the plan again. Cases after the "
        f"cursor (position {execution['cursor_ordinal']}) take corrections "
        "without an abort."
    )


def correct_live_rosters(conn: Any, requirement_ids: Iterable[int]) -> list[str]:
    """Rebuild unreached live roster entries for rows just rewritten.

    Call after the rows are written, inside the same transaction. Returns the
    corrected execution ids. Raises :class:`QaPlanError` naming the abort when
    a reached case changed, an unreached case was retired, or a correction
    would move a case or the walk's target; the caller's rollback then leaves
    every row and roster as it was.
    """
    from yoke_core.domain.qa_plan_execution_target_snapshot import (
        execution_target_for_roster,
    )
    from yoke_core.domain.qa_plan_management import QaPlanError

    corrected: list[str] = []
    for execution, held in _holders(
        conn, {int(rid) for rid in requirement_ids}, lock=True
    ):
        recorded = {row["ordinal"] for row in result_rows(conn, execution["id"])}
        roster = [dict(entry) for entry in execution["roster"]]
        for ordinal, entry in held:
            reached = _reached(execution, ordinal, recorded)
            rebuilt = _rebuilt(conn, execution, entry)
            if rebuilt is None:
                if reached:
                    continue  # its result already stands for it
                raise QaPlanError(
                    _refusal(
                        conn,
                        execution,
                        ordinal,
                        "was retired before the walk reached it",
                    )
                )
            if _definition(rebuilt) == _definition(entry):
                continue
            if reached:
                raise QaPlanError(
                    _refusal(
                        conn,
                        execution,
                        ordinal,
                        "has already been reached, so its definition is part of what the walk judged",
                    )
                )
            row = query_one(
                conn,
                "SELECT case_position,baseline_position FROM qa_requirements "
                f"WHERE id={marker(conn)}",
                (int(entry["requirement_id"]),),
            )
            if any(
                row[key] is not None and int(row[key]) != int(entry[key])
                for key in ("case_position", "baseline_position")
            ):
                raise QaPlanError(
                    _refusal(
                        conn,
                        execution,
                        ordinal,
                        "would move to a different place in the walk's order",
                    )
                )
            roster[ordinal] = rebuilt
        if roster == execution["roster"]:
            continue
        stored_target = execution.get("execution_target_digest")
        if stored_target and execution_target_for_roster(roster)[1] != stored_target:
            raise QaPlanError(
                _refusal(
                    conn,
                    execution,
                    held[0][0],
                    "would change the target the walk runs against",
                )
            )
        conn.execute(
            f"UPDATE qa_plan_executions SET roster_json={marker(conn)},"
            f"roster_digest={marker(conn)} WHERE id={marker(conn)}",
            (canonical(roster), roster_digest(roster), str(execution["id"])),
        )
        corrected.append(str(execution["id"]))
    return corrected


LIVE_EXECUTION_CODE = "plan_execution_in_flight"


def carry_into_live_rosters(
    conn: Any,
    *,
    subject: str,
    rewritten: list[int],
    created: list[int],
    **live_subject: Any,
) -> None:
    """After a plan refresh's writes: correct unreached roster entries, or refuse.

    A created row would add a case the live walk's roster does not carry, so
    it refuses with the abort; rewritten and retired rows go to
    :func:`correct_live_rosters`, which reaches only cases not yet walked.
    """
    if created:
        require_no_live_execution(conn, subject=subject, **live_subject)
    correct_live_rosters(conn, rewritten)


def require_no_live_execution(
    conn: Any,
    *,
    subject: str,
    item_id: int | None = None,
    transition_id: str | None = None,
    deployment_run_id: str | None = None,
    deployment_stage: str | None = None,
    deployment_member_item_id: int | None = None,
) -> None:
    """Refuse a refresh whose rows a live execution has already frozen in."""
    from yoke_core.domain.qa_plan_execution_store import live_plan_execution_id
    from yoke_core.domain.qa_plan_management import QaPlanError

    if not _table_exists(conn, "qa_plan_executions"):
        return
    if deployment_stage and deployment_member_item_id is None:
        from yoke_core.domain.qa_stage_execution_holders import live_stage_executions

        # Every session's stage-wide walk froze rows from this subject.
        live = live_stage_executions(
            conn,
            deployment_run_id=str(deployment_run_id),
            deployment_stage=deployment_stage,
        )
        execution_id = str(live[0]["id"]) if live else None
    else:
        execution_id = live_plan_execution_id(
            conn,
            item_id=item_id,
            transition_id=transition_id,
            deployment_run_id=deployment_run_id,
            deployment_stage=deployment_stage,
            deployment_member_item_id=deployment_member_item_id,
        )
    if execution_id is None:
        return
    raise QaPlanError(
        f"{LIVE_EXECUTION_CODE}: {subject} is being walked by live QA plan "
        f"execution {execution_id}, whose roster was frozen from these rows. "
        "Refreshing them now would move the definitions underneath a walk "
        "already in progress. Abort that execution with `yoke qa plan abort "
        f'--execution-id {execution_id} --reason "<why>"`, then refresh and '
        "start the walk again — the abort is what makes the refresh reachable."
    )


__all__ = [
    "LIVE_EXECUTION_CODE",
    "ROSTER_CASE_REACHED_CODE",
    "carry_into_live_rosters",
    "correct_live_rosters",
    "reached_by_live_execution",
    "require_no_live_execution",
]
