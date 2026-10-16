"""Require terminal stages and settled run-bound plan cases for completion.

Plan cases use the shared obligation settlement rule and current passing
evidence, matching the acceptance checks at each QA stage.
"""

from __future__ import annotations

import json
from typing import Any, List, Optional

from yoke_core.domain.db_helpers import query_rows, query_scalar
from yoke_core.domain.qa_obligation_settlement import settled_obligation_sql
from yoke_core.domain.qa_requirement_pass_currency import has_current_passing_run
from yoke_core.domain.schema_common import _table_exists

#: Leads the pipeline report when stages delivered but blocking QA has not
#: settled. Deliberately not the finalization-pending wording, which says
#: the deploy succeeded — here it has not.
AWAITING_QA_PREFIX = "deploy stages complete, blocking QA unresolved"

#: Leads the report when the run-completing stage was held back before it
#: ran. Distinct from :data:`AWAITING_QA_PREFIX` because the stages are
#: *not* complete: one is deliberately unstarted, and saying otherwise is
#: the false-completion this hold exists to prevent.
HELD_STAGE_PREFIX = "final stage held, blocking QA unresolved"


def unresolved_blocking_qa(conn: Any, run_id: str) -> List[str]:
    """Describe the run-bound plan cases that remain unsettled."""
    return _unresolved_plan_cases(conn, run_id)


def _unresolved_plan_cases(conn: Any, run_id: str) -> List[str]:
    """Run-bound ``qa_requirements`` rows with no passing run, still owed.

    "Still owed" is the shared settlement rule, so a row a passing
    replacement superseded reads the same here as it does at the stage that
    accepted the supersession in the first place.
    """
    if not (_table_exists(conn, "qa_requirements") and _table_exists(conn, "qa_runs")):
        return []
    rows = query_rows(
        conn,
        f"""
        SELECT r.id, r.qa_kind FROM qa_requirements r
        WHERE r.deployment_run_id = %s
          AND r.blocking_mode = 'blocking'
          AND NOT {settled_obligation_sql(conn, "r")}
        ORDER BY r.id ASC
        """,
        (run_id,),
    )
    rows = [row for row in rows if not has_current_passing_run(conn, int(row["id"]))]
    if not rows:
        return []
    from yoke_core.domain.qa_review_requests import requirement_awaits_human_review

    described = []
    for row in rows:
        waiting = requirement_awaits_human_review(conn, int(row["id"]))
        described.append(
            waiting.detail
            if waiting
            else f"requirement #{row['id']} ({row['qa_kind']}): no passing run"
        )
    return described


def blocking_obligation_total(conn: Any, run_id: str) -> int:
    """How many blocking QA obligations *run_id* carries in total.

    Counted from the same plan cases :func:`unresolved_blocking_qa` reads, so
    "M of P outstanding" is always a subset relation rather than two
    numbers from two different populations.
    """
    total = 0
    if _table_exists(conn, "qa_requirements"):
        total += int(
            query_scalar(
                conn,
                "SELECT COUNT(*) FROM qa_requirements "
                "WHERE deployment_run_id=%s AND blocking_mode='blocking' "
                f"AND NOT {settled_obligation_sql(conn)}",
                (run_id,),
            )
            or 0
        )
    return total


def redrive_recovery(run_id: str, *, unresolved: int) -> str:
    """Name automatic continuation and point at the recovery surfaces.

    One line, because this rides every waiting report and every red run row:
    the options for a run that stalls live in ``yoke deployment-runs
    remove-item --help`` and the run read, not repeated in each copy.
    """
    if unresolved:
        return (
            "The run finishes by itself when blocking QA settles. "
            f"Blocking QA remains: `yoke deployment-runs get {run_id}` (red member: "
            "`yoke deployment-runs remove-item --help`)."
        )
    return (
        "Nothing is outstanding; automatic completion should finish this run. "
        f"If it stays executing, read `yoke deployment-runs get {run_id}` "
        f"and re-drive {run_id}."
    )


def awaiting_qa_report_lines(run_id: str, unresolved: List[str]) -> List[str]:
    """Render the pipeline's waiting report for unresolved blocking QA."""
    return [
        f"{AWAITING_QA_PREFIX} — {len(unresolved)} blocking QA "
        f"obligation(s) unresolved for run {run_id}",
        *(f"  - {detail}" for detail in unresolved),
        f"  {redrive_recovery(run_id, unresolved=len(unresolved))}",
    ]


def held_stage_report_lines(
    run_id: str,
    stage_name: str,
    unresolved: List[str],
    *,
    obligation_count: Optional[int] = None,
) -> List[str]:
    """Render the report for a run-completing stage held before it ran."""
    count = len(unresolved) if obligation_count is None else obligation_count
    return [
        f"{HELD_STAGE_PREFIX} — stage {stage_name!r} stays pending while "
        f"{count} blocking QA obligation(s) are unresolved for "
        f"run {run_id}",
        *(f"  - {detail}" for detail in unresolved),
        f"  {redrive_recovery(run_id, unresolved=count)}",
    ]


def refuse_succeeded(
    conn: Any,
    run_id: str,
    *,
    force: bool = False,
) -> Optional[str]:
    """Return why *run_id* may not be stamped succeeded, or ``None``.

    ``force`` is the operator override the run-update surface already
    carries; it suppresses the refusal exactly as it does for the stage
    checks, and never for a defect in the caller's own request.
    """
    stage_refusal = _refuse_on_stage(conn, run_id, force=force)
    if stage_refusal:
        return stage_refusal
    if force:
        return None
    unresolved = unresolved_blocking_qa(conn, run_id)
    if not unresolved:
        return None
    detail = "; ".join(unresolved)
    return (
        f"Error: cannot set status=succeeded -- {len(unresolved)} blocking QA "
        f"obligation(s) unresolved for run {run_id}: {detail}. "
        + redrive_recovery(run_id, unresolved=len(unresolved))
    )


def _refuse_on_stage(
    conn: Any,
    run_id: str,
    *,
    force: bool,
) -> Optional[str]:
    """Refuse a succeeded stamp the run's recorded stage contradicts."""
    cur_stage = (
        query_scalar(
            conn,
            "SELECT COALESCE(current_stage, '') FROM deployment_runs WHERE id=%s",
            (run_id,),
        )
        or ""
    )
    if not cur_stage or force:
        return None
    if cur_stage.endswith("-failed"):
        return (
            f"Error: cannot set status=succeeded -- "
            f"current_stage '{cur_stage}' indicates failure"
        )
    final_stage = _final_stage_name(conn, run_id)
    if final_stage and cur_stage not in (final_stage, "complete"):
        return (
            f"Error: cannot set status=succeeded -- "
            f"current_stage '{cur_stage}' is not the final stage"
        )
    return None


def _final_stage_name(conn: Any, run_id: str) -> str:
    """Name the last stage of the run's flow, empty when unreadable."""
    run_flow = query_scalar(
        conn, "SELECT flow FROM deployment_runs WHERE id=%s", (run_id,)
    )
    if not run_flow:
        return ""
    stages_json = query_scalar(
        conn, "SELECT stages FROM deployment_flows WHERE id=%s", (run_flow,)
    )
    if not stages_json:
        return ""
    try:
        stages = json.loads(stages_json)
        return str(stages[-1].get("name", "")) if stages else ""
    except (json.JSONDecodeError, IndexError, KeyError, AttributeError):
        return ""


__all__ = [
    "AWAITING_QA_PREFIX",
    "awaiting_qa_report_lines",
    "blocking_obligation_total",
    "held_stage_report_lines",
    "HELD_STAGE_PREFIX",
    "redrive_recovery",
    "refuse_succeeded",
    "unresolved_blocking_qa",
]
