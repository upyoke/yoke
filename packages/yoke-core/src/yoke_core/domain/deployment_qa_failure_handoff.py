"""Give a failed item-scoped release QA case to its correction owner."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from yoke_core.domain.deployment_run_driver_notice import push_member_notice
from yoke_core.domain.merge_queue_landing_notice import HOLDER
from yoke_core.domain.project_identity import render_item_ref, resolve_project


def failure_handoff_key(
    run_id: str, stage: str, item_id: int, target_digest: str, verdict_run_id: int
) -> str:
    """One handoff per failed verdict on the stage's frozen target."""
    return (
        f"deployment-qa-member-failure:{run_id}:{stage}:{item_id}:"
        f"{target_digest}:{verdict_run_id}"
    )


def failure_handoff_message(
    *,
    run_id: str,
    stage: str,
    item_ref: str,
    project_slug: str,
    requirement_ids: tuple[int, ...],
    route: str,
) -> str:
    """State the evidence and the two correction routes without guessing cause."""
    failed = ", ".join(f"#{value}" for value in requirement_ids)
    evidence = " ".join(
        f"`yoke qa requirement get --requirement-id {value}` and "
        f"`yoke qa run list --requirement-id {value}`"
        for value in requirement_ids
    )
    owner = (
        "You hold this item's work claim."
        if route == HOLDER
        else "The item holder is gone; staff or claim this item before changing it."
    )
    return (
        f"Deployment run {run_id} stage {stage!r} has failed item QA "
        f"requirement(s) {failed} for {item_ref}. {owner} Read "
        f"`yoke deployment-runs get {run_id}` and {evidence} to determine "
        "whether the deployed environment or member code caused the failure. "
        "If the environment failed, keep the item in release and run fresh "
        "QA against this same deployed revision: `yoke watch qa-plan -- "
        f"--deployment-run-id {run_id} --stage {stage} --member {item_ref} "
        f"--project {project_slug}`. If the evidence establishes a member "
        "code defect, refresh any survey required by the pinned workflow, "
        "then use its ordinary rework route: "
        f"`yoke lifecycle transition {item_ref} --from release --to "
        "implementing --reason 'Post-deploy QA found a member code defect'`. "
        "Keep the same work claim and worktree; verify and merge the correction. "
        "Have the run driver settle the old run without changing its pin. "
        "The failed run and QA remain history, and a new run must deploy the "
        "corrected commit. This backward transition needs no operator approval."
    )


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
    item = conn.execute(
        "SELECT project_id FROM items WHERE id=%s", (int(item_id),)
    ).fetchone()
    if item is None:
        return f"failed: member item {item_id} is missing; inspect run {run_id}"
    project_id = int(item["project_id"] if hasattr(item, "keys") else item[0])
    project = resolve_project(conn, project_id)
    item_ref = render_item_ref(conn, int(item_id))
    placeholders = ",".join("%s" for _ in requirement_ids)
    row = conn.execute(
        f"SELECT MAX(id) AS latest_id FROM qa_runs WHERE qa_requirement_id IN ({placeholders})",
        requirement_ids,
    ).fetchone()
    latest = int((row["latest_id"] if hasattr(row, "keys") else row[0]) or 0)
    key = failure_handoff_key(
        run_id, stage, item_id, str(status.get("target_digest") or ""), latest
    )
    savepoint = "_yoke_member_qa_failure_notice"
    try:
        conn.execute(f"SAVEPOINT {savepoint}")
        delivery = push_member_notice(
            conn,
            item_id=item_id,
            project_id=project_id,
            body_for_route=lambda route: failure_handoff_message(
                run_id=run_id,
                stage=stage,
                item_ref=item_ref,
                project_slug=project.slug,
                requirement_ids=requirement_ids,
                route=route,
            ),
            idempotency_key=key,
            now=datetime.now(timezone.utc),
        )
        conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        conn.commit()
    except Exception as exc:  # noqa: BLE001 - preserve the failed QA verdict
        from yoke_core.domain.db_optional_queries import rollback_savepoint

        rollback_savepoint(conn, savepoint)
        return f"failed: {exc}; inspect run {run_id} stage {stage!r}"
    if not delivery:
        return (
            f"unaddressed: no member claim holder or project {project.slug} "
            f"steering seat; staff {item_ref} and inspect run {run_id}"
        )
    return delivery


__all__ = [
    "failure_handoff_key",
    "failure_handoff_message",
    "notify_member_qa_failure",
]
