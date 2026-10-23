"""Give a failed item-scoped release QA case to its correction owner."""

from __future__ import annotations

from yoke_contracts.timestamps import utc_now
from typing import Any, Mapping

from yoke_core.domain.db_savepoint import SavepointLostError, savepoint
from yoke_core.domain.deployment_run_driver_notice import push_member_notice
from yoke_core.domain.json_helper import loads_text
from yoke_core.domain.merge_queue_landing_notice import resolve_lane_recipient
from yoke_core.domain.project_identity import render_item_ref, resolve_project

#: Identity every member QA failure handoff shares, ahead of its run/stage/item.
FAILURE_HANDOFF_PREFIX = "deployment-qa-member-failure:"


def failure_handoff_key(
    run_id: str, stage: str, item_id: int, target_digest: str, verdict_run_id: int
) -> str:
    """One handoff per failed verdict on the stage's frozen target."""
    return (
        f"{FAILURE_HANDOFF_PREFIX}{run_id}:{stage}:{item_id}:"
        f"{target_digest}:{verdict_run_id}"
    )


def item_stage_retry_command(*, item_ref: str, stage: str, project: str) -> str:
    """The item-scoped retry. A deployment-run id refuses an item stage."""
    return (
        f"yoke qa plan run --item {item_ref} --stage {stage} --project {project}"
    )


def retry_command_for_stage(
    conn: Any,
    *,
    run_id: str,
    stage: str,
    member_ref: str | None,
    member_id: int | None,
    project: str | None,
) -> str:
    """Item stages retry by item; run stages keep the run id."""
    if not member_ref and member_id is None:
        return f"yoke qa plan run --deployment-run-id {run_id} --stage {stage}"
    if not member_ref:
        member_ref = render_item_ref(conn, int(member_id))
    if not project and member_id is not None:
        row = conn.execute(
            "SELECT p.slug FROM projects p JOIN items i ON i.project_id=p.id "
            "WHERE i.id=%s",
            (int(member_id),),
        ).fetchone()
        project = "" if row is None else str(row["slug"] if hasattr(row, "keys") else row[0])
    return item_stage_retry_command(
        item_ref=str(member_ref), stage=stage, project=str(project or "")
    )


def failure_handoff_message(
    *,
    run_id: str,
    stage: str,
    item_ref: str,
    requirement_ids: tuple[int, ...],
    project: str = "",
    retry: bool = False,
) -> str:
    """Keep the hook notice inline; the command help owns recovery."""
    failed = ", ".join(f"#{value}" for value in requirement_ids)
    head = (
        f"Deployment run {run_id} stage {stage!r} has failed item QA "
        f"requirement(s) {failed} for {item_ref}"
    )
    if retry:
        command = item_stage_retry_command(
            item_ref=item_ref, stage=stage, project=project
        )
        return (
            f"{head}, recorded before this release took over. The current "
            f"release contains the item's merge; retry the case: `{command}`."
        )
    return (
        f"{head}; recovery: `yoke qa plan run --help`."
        " Classify the failure and start rework or record its blocker."
    )


def _transferred_requirements(
    conn: Any, run_id: str, requirement_ids: tuple[int, ...]
) -> set[int]:
    """Failed requirements frozen by an ancestor run this release took over."""
    from yoke_core.domain.deployment_qa_takeover_identity import inherited_target

    placeholders = ",".join("%s" for _ in requirement_ids)
    rows = conn.execute(
        "SELECT id,execution_target_json FROM qa_requirements "
        f"WHERE id IN ({placeholders})",
        requirement_ids,
    ).fetchall()
    return {
        int(row[0])
        for row in rows
        if row[1]
        and inherited_target(
            conn,
            run_id,
            dict(row[1]) if isinstance(row[1], Mapping) else loads_text(str(row[1])),
        )
    }


def _merge_contained(conn: Any, run_id: str, item_id: int, project_id: int) -> bool:
    """Whether the run's pinned source provably contains the item's merge."""
    from yoke_core.domain.delivery_evidence_ladder import item_merge_identity
    from yoke_core.domain import deployment_run_candidate_containment as containment
    from yoke_core.domain.deployment_run_project_sources import run_source_sha

    merge = item_merge_identity(conn, item_id)
    lineage = run_source_sha(conn, run_id, project_id)
    if not merge or not lineage:
        return False
    verdict = containment.candidate_contains_commit(
        conn, project_id, candidate_lineage=lineage, commit_sha=merge
    )
    return verdict.state == containment.CONTAINED


def notify_member_qa_failure(
    conn: Any,
    *,
    run_id: str,
    stage: str,
    item_id: int,
    status: Mapping[str, Any],
) -> str:
    """Reach the member holder or its own project's steering seat.

    A notification problem cannot turn failed QA into an accepted stage.
    The caller still sees the run's failed status and a named delivery miss.
    """
    if status.get("outcome") != "blocked":
        return ""
    failures = status.get("case_failures") or ()
    requirement_ids = tuple(
        sorted(
            {
                int(failure["requirement_id"])
                for failure in failures
                if failure.get("kind") == "red" and int(failure["requirement_id"]) > 0
            }
        )
    )
    if not requirement_ids:
        return ""
    from yoke_core.domain.deployment_member_candidate_release import (
        release_failed_member,
    )

    if release_failed_member(conn, run_id=run_id, stage=stage, item_id=item_id):
        return "released: recorded correction rides a later release"
    item = conn.execute(
        "SELECT project_id FROM items WHERE id=%s", (int(item_id),)
    ).fetchone()
    if item is None:
        return f"failed: member item {render_item_ref(conn, item_id)} is missing; inspect run {run_id}"
    project_id = int(item["project_id"] if hasattr(item, "keys") else item[0])
    project = resolve_project(conn, project_id)
    item_ref = render_item_ref(conn, int(item_id))
    recipient, _, _ = resolve_lane_recipient(
        conn, item_id=item_id, project_id=project_id
    )
    # A FAIL carried across a takeover into a release that contains the
    # item's merge is retried, so its owner is told even when it produced
    # that verdict itself.
    retry = set(requirement_ids) <= _transferred_requirements(
        conn, run_id, requirement_ids
    ) and _merge_contained(conn, run_id, int(item_id), project_id)
    placeholders = ",".join("%s" for _ in requirement_ids)
    from yoke_core.domain.qa_latest_execution import latest_executions

    latest_by_requirement = {
        rid: int(attempt["id"])
        for rid, attempt in latest_executions(conn, requirement_ids).items()
    }
    if recipient and not retry:
        # The execution records own the verdict producer; performed_by names
        # a runner, not the session that already received its result.
        results = conn.execute(
            "SELECT r.requirement_id,r.result_json FROM qa_plan_execution_results r "
            "JOIN qa_plan_executions e ON e.id=r.execution_id "
            f"WHERE e.session_id=%s AND r.requirement_id IN ({placeholders})",
            (recipient, *requirement_ids),
        ).fetchall()
        self_verdicts = {
            int(row[0])
            for row in results
            if loads_text(str(row[1])).get("run_id")
            == latest_by_requirement.get(int(row[0]))
        }
        requirement_ids = tuple(
            value for value in requirement_ids if value not in self_verdicts
        )
        if not requirement_ids:
            return ""
    latest = max(
        (latest_by_requirement.get(value, 0) for value in requirement_ids), default=0
    )
    key = failure_handoff_key(
        run_id, stage, item_id, str(status.get("target_digest") or ""), latest
    )
    try:
        with savepoint(conn, "_yoke_member_qa_failure_notice", owns=False):
            delivery = push_member_notice(
                conn,
                item_id=item_id,
                project_id=project_id,
                body_for_route=lambda route: failure_handoff_message(
                    run_id=run_id,
                    stage=stage,
                    item_ref=item_ref,
                    requirement_ids=requirement_ids,
                    project=project.slug,
                    retry=retry,
                ),
                idempotency_key=key,
                now=utc_now(),
            )
        conn.commit()
    except SavepointLostError:
        raise
    except Exception as exc:  # noqa: BLE001 - preserve the failed QA verdict
        return f"failed: {exc}; inspect run {run_id} stage {stage!r}"
    if not delivery:
        return (
            f"unaddressed: no member claim holder or project {project.slug} "
            f"steering seat; staff {item_ref} and inspect run {run_id}"
        )
    return delivery


__all__ = [
    "FAILURE_HANDOFF_PREFIX",
    "failure_handoff_key",
    "failure_handoff_message",
    "item_stage_retry_command",
    "notify_member_qa_failure",
    "retry_command_for_stage",
]
