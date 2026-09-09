"""What must hold before a deployment run may be stamped succeeded.

A run reaches its final stage and a run has delivered are different
facts. The stage checks here answer the first — the recorded stage is a
real terminal stage of the run's own flow, and it did not fail. The QA
scan answers the second: every blocking check the run carries has an
outcome a person or a runner actually produced.

Blocking QA lives in two places because it arrives two ways.
``deployment_run_qa`` carries the flow-derived checks seeded from the
flow's stages, keyed by check name. ``qa_requirements`` carries the
run's plan cases, keyed by ``deployment_run_id`` and satisfied by a
passing row in ``qa_runs``. Neither is a projection of the other, so a
completion boundary that reads one of them still lets the other through.

Only ``passed`` and ``waived`` resolve a flow-derived check. Everything
else is unresolved, and that deliberately includes ``failed``: a failed
blocking check is the strongest reason not to call a run succeeded, and
reading it as resolved because it is no longer pending is the shape this
module exists to prevent.
"""

from __future__ import annotations

import json
from typing import Any, List, Optional

from yoke_core.domain.db_helpers import query_rows, query_scalar
from yoke_core.domain.schema_common import _table_exists

#: Flow-derived ``deployment_run_qa`` statuses that settle a blocking check.
RESOLVED_RUN_QA_STATUSES = ("passed", "waived")

#: Leads the pipeline report when stages delivered but blocking QA has not
#: settled. Deliberately not the finalization-pending wording, which says
#: the deploy succeeded — here it has not.
AWAITING_QA_PREFIX = "deploy stages complete, blocking QA unresolved"


def unresolved_blocking_qa(conn: Any, run_id: str) -> List[str]:
    """Describe every blocking QA obligation *run_id* has not settled.

    Returns one operator-readable line per unresolved obligation, empty
    when the run is free to complete. A universe whose schema predates
    either table reports nothing from that table rather than failing —
    the completion boundary runs against fixtures that carry only the
    deployment tables they exercise.
    """
    return _unresolved_flow_checks(conn, run_id) + _unresolved_plan_cases(
        conn, run_id
    )


def _unresolved_flow_checks(conn: Any, run_id: str) -> List[str]:
    """Flow-derived ``deployment_run_qa`` checks without a settled status."""
    if not _table_exists(conn, "deployment_run_qa"):
        return []
    placeholders = ", ".join(["%s"] * len(RESOLVED_RUN_QA_STATUSES))
    rows = query_rows(
        conn,
        "SELECT check_name, status FROM deployment_run_qa "
        f"WHERE run_id=%s AND blocking=1 AND status NOT IN ({placeholders}) "
        "ORDER BY check_name ASC",
        (run_id, *RESOLVED_RUN_QA_STATUSES),
    )
    return [
        f"check '{row['check_name']}' is {row['status']}" for row in rows
    ]


def _unresolved_plan_cases(conn: Any, run_id: str) -> List[str]:
    """Run-bound ``qa_requirements`` rows with no passing run and no waiver."""
    if not (
        _table_exists(conn, "qa_requirements") and _table_exists(conn, "qa_runs")
    ):
        return []
    rows = query_rows(
        conn,
        """
        SELECT r.id, r.qa_kind FROM qa_requirements r
        WHERE r.deployment_run_id = %s
          AND r.blocking_mode = 'blocking'
          AND r.waived_at IS NULL
          AND NOT EXISTS (
            SELECT 1 FROM qa_runs qr
            WHERE qr.qa_requirement_id = r.id
              AND qr.verdict = 'pass'
          )
        ORDER BY r.id ASC
        """,
        (run_id,),
    )
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


def awaiting_qa_report_lines(run_id: str, unresolved: List[str]) -> List[str]:
    """Render the pipeline's waiting report for unresolved blocking QA."""
    return [
        f"{AWAITING_QA_PREFIX} — {len(unresolved)} blocking QA "
        f"obligation(s) unresolved for run {run_id}",
        *(f"  - {detail}" for detail in unresolved),
        f"  Settle or waive each one, then re-drive {run_id} to finalize.",
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
        "Settle or waive each one through its registered QA surface, then "
        f"re-drive {run_id} to finalize."
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
    "RESOLVED_RUN_QA_STATUSES",
    "refuse_succeeded",
    "unresolved_blocking_qa",
]
