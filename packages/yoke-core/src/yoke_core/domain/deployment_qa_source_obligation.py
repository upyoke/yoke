"""Whether one intake source obligation is accepted on the completion run."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.qa_item_obligation_queries import (
    unsatisfied_blocking as unsatisfied_blocking,
)
from yoke_core.domain.deployment_item_completion_runs import (
    completion_runs,
    latest_qa_member_run,
)
from yoke_core.domain.qa_requirement_source_retirement import (
    lineage_identity_clause,
)
from yoke_core.domain.deployment_qa_execution_target import (
    deployment_qa_execution_target,
)
from yoke_core.domain.deployment_qa_member_scope import legacy_run_credits_run_wide
from yoke_core.domain.deployment_qa_run_bound_done_settlement import (
    run_bound_row_satisfied_at_done,
)
from yoke_core.domain.deployment_qa_stage_acceptance import (
    latest_verdict,
    stage_acceptance_blockers,
)
from yoke_core.domain.deployment_qa_stage_contract import (
    DEPLOYMENT_STAGE_ACCEPTANCE_QA_KIND,
    deployment_qa_stage_subject,
)
from yoke_core.domain.qa_obligation_settlement import (
    obligation_settled,
    requirement_retracted_at_select,
)

# Intake recovery wording is pinned in test_post_deploy_recovery_exit_conditions.py.
POST_DEPLOY_RECOVERY = (
    "A post_deploy obligation is satisfied by its admitted copy on the selected "
    "completion member (run-wide for a legacy schema-1 run); re-running intake "
    "cannot clear it. If no admitted copy "
    "was accepted because no final delivery or matching QA target exists, deliver "
    "the item through a flow whose stage target matches target_env and finish "
    "its required delivery and QA. If a corrected case bound to the same run, "
    "stage, member, and target already passed, use `yoke qa requirement "
    "supersede` for the defective copy; finished runs refuse new bound cases. "
    "If no correction can apply, waive the requirement through the registered "
    "surface with explicit authorization. Every admitted duplicate must be "
    "accepted, superseded, or waived. A failed run-bound case needs a passing "
    "same-run, stage, member, and target replacement with accepted stage proof "
    "or an authorized waiver; another delivery cannot settle it."
)


def latest_completion_run(
    conn: Any, item_id: int, *, skip_terminal_failures: bool = False
) -> dict[str, Any] | None:
    """Newest membership that can close this item, or none.

    Walks :func:`completion_runs`, the one reading of completion authority.
    A failed or cancelled attempt never shadows a live or delivered one,
    whichever is newer: a duplicate cancelled before it executed says nothing
    about the release that is settling or succeeded beside it, while a newer
    active attempt still wins and must finish first. The newest failed or
    cancelled run is answered only when no other membership exists, so its
    status can still be reported — unless ``skip_terminal_failures`` asks for
    none, which source QA does.
    """
    runs = completion_runs(conn, int(item_id))
    for run in runs:
        if run["status"] not in _TERMINAL_FAILURES:
            return run
    if skip_terminal_failures or not runs:
        return None
    return runs[0]


_TERMINAL_FAILURES = frozenset({"failed", "cancelled"})


def _row_value(row: Any, key: str, position: int) -> Any:
    return row[key] if hasattr(row, "keys") else row[position]


def latest_deployment_run_for_item(conn: Any, item_id: int) -> dict[str, str]:
    """Return the registered ``done_transition.latest_deployment_run`` binding.

    Empty ``run_id`` and ``status`` mean the item has no completion-flow run."""
    row = latest_completion_run(conn, int(item_id))
    if row is None:
        return {"run_id": "", "status": ""}
    return {"run_id": row["id"], "status": row["status"]}


def source_obligation_consumed(
    conn: Any, *, item_id: int, source_requirement_id: int
) -> bool:
    """Require accepted proof from the member answering this source's target.

    A newer active member holds the wait; a containment-only release has no
    copies. Scoped runs match source/member identity, including copies of any
    source retired in this one's favor on the run that admitted it. Schema-1 runs
    answer through their nonempty shared blocking post-deploy set, using the
    same reader as settlement. Every copy and replacement must pass or be
    discharged; an unsettled duplicate or bad replacement still blocks done.
    """
    # Containment-only releases prove delivery, but have no member-scoped QA
    # copy. Read the completion membership that actually admitted this source.
    from yoke_core.domain.deployment_member_post_deploy_admission import (
        requirement_target_environment,
    )

    source_target = conn.execute(
        "SELECT target_env,execution_target_json FROM qa_requirements WHERE id=%s AND item_id=%s",
        (int(source_requirement_id), int(item_id)),
    ).fetchone()
    if source_target is None:
        return False
    completion = latest_qa_member_run(
        conn,
        item_id=int(item_id),
        target_env=requirement_target_environment(source_target[0], source_target[1]),
    )
    if completion is None:
        return False
    if completion["status"] != "succeeded":
        from yoke_core.domain.deployment_member_independent_close_out import (
            independent_member_delivery_ready,
        )

        if not independent_member_delivery_ready(
            conn, item_id=int(item_id), run_id=str(completion["id"])
        ):
            return False
    run_id = completion["id"]
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    source_row = conn.execute(
        "SELECT id,item_id,plan_id,plan_case_key FROM qa_requirements "
        f"WHERE id={marker}",
        (int(source_requirement_id),),
    ).fetchone()
    if source_row is None:
        return False
    source = {
        key: _row_value(source_row, key, position)
        for position, key in enumerate(("id", "item_id", "plan_id", "plan_case_key"))
    }
    if source["item_id"] != int(item_id):
        return False
    legacy = legacy_run_credits_run_wide(conn, run_id=run_id, item_id=item_id)
    if legacy:
        identity = "qa_phase='post_deploy' AND blocking_mode='blocking'"
        identity_params = ()
    else:
        identity, identity_params = lineage_identity_clause(conn, source, marker=marker)
    member_scope = f"deployment_member_item_id={marker}"
    if legacy:
        member_scope = f"({member_scope} OR deployment_member_item_id IS NULL)"
    rows = conn.execute(
        "SELECT id,deployment_stage,deployment_member_item_id,"
        f"waived_at,superseded_by_requirement_id,{requirement_retracted_at_select(conn)} "
        "FROM qa_requirements WHERE deployment_run_id="
        f"{marker} AND {member_scope} AND {identity} "
        "ORDER BY id",
        (run_id, int(source["item_id"]), *identity_params),
    ).fetchall()
    if not rows:
        return False
    if legacy:
        from yoke_core.domain.no_obligation_member_close_out import (
            satisfied_delivery_member,
        )

        # Corrections can change case identity; the run-wide gate also reads
        # their successors, just as scoped stage acceptance does below.
        if not satisfied_delivery_member(conn, run_id=run_id, item_id=item_id):
            return False
    else:
        row = rows[0]
        stage_name = str(_row_value(row, "deployment_stage", 1) or "")
        member = _row_value(row, "deployment_member_item_id", 2)
        member_item_id = int(member) if member not in (None, 0) else None
        try:
            subject = deployment_qa_stage_subject(
                conn,
                run_id=run_id,
                stage_name=stage_name,
                member_item_id=member_item_id,
                require_active=False,
            )
            target = deployment_qa_execution_target(conn, subject)
            blockers = stage_acceptance_blockers(
                conn,
                subject=subject,
                target=target,
                acceptance_qa_kind=DEPLOYMENT_STAGE_ACCEPTANCE_QA_KIND,
            )
        except (LookupError, TypeError, ValueError):
            return False
        if blockers:
            return False
    for row in rows:
        copy_id = int(_row_value(row, "id", 0))
        settled = obligation_settled(
            {
                "waived_at": _row_value(row, "waived_at", 3),
                "superseded_by_requirement_id": _row_value(
                    row, "superseded_by_requirement_id", 4
                ),
                "retracted_at": _row_value(row, "retracted_at", 5),
            }
        )
        if not settled and latest_verdict(conn, copy_id) != "pass":
            return False
    return True


def blocking_row_unsatisfied_at_done(
    conn: Any,
    *,
    item_id: int,
    source_requirement_id: int,
    qa_phase: str,
    original_passed: bool,
) -> bool:
    """True when this blocking intake row still holds ``done``.

    A ``post_deploy`` row needs its completion member's admitted proof; its
    own earlier pass could describe another candidate. Other phases keep
    their original passing run as proof.
    """
    if qa_phase != "post_deploy":
        return not original_passed
    return not source_obligation_consumed(
        conn, item_id=int(item_id), source_requirement_id=int(source_requirement_id)
    )


def row_unsatisfied_at_done(conn: Any, row: Any, *, item_id: int) -> bool:
    """:func:`blocking_row_unsatisfied_at_done` over a queried requirement row.

    Callers select the original row's own pass rather than filtering on it
    in SQL, so a ``post_deploy`` row that already passed is still judged.
    """
    if hasattr(row, "keys"):
        phase = str(row["qa_phase"] or "")
        source_id = int(row["id"])
        passed = bool(row["passed"])
        if row.get("item_id") is None:
            if phase == "post_deploy" and not passed and row["deployment_run_id"]:
                return not run_bound_row_satisfied_at_done(
                    conn,
                    requirement_id=source_id,
                    item_id=item_id,
                    completion=latest_completion_run(conn, item_id),
                )
            phase = ""
    else:
        phase = str(row[1] or "")
        source_id = int(row[0])
        passed = bool(row[2])
    return blocking_row_unsatisfied_at_done(
        conn,
        item_id=int(item_id),
        source_requirement_id=source_id,
        qa_phase=phase,
        original_passed=passed,
    )


@dataclass(frozen=True)
class UnsatisfiedBlocking:
    """The item's still-unsatisfied blocking requirements, and their shape.

    ``includes_post_deploy`` is what a refusal needs in order to name the
    right recovery: a post_deploy row is cleared by delivery or by a waiver,
    never by executing the case again.
    """

    count: int = 0
    includes_post_deploy: bool = False
    rows: tuple[dict[str, Any], ...] = ()


__all__ = [
    "POST_DEPLOY_RECOVERY",
    "UnsatisfiedBlocking",
    "blocking_row_unsatisfied_at_done",
    "latest_completion_run",
    "latest_deployment_run_for_item",
    "row_unsatisfied_at_done",
    "source_obligation_consumed",
    "unsatisfied_blocking",
]
