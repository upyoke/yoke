"""Give a failed item-scoped release QA case to its correction owner."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from yoke_core.domain.deployment_run_driver_notice import push_member_notice
from yoke_core.domain.json_helper import loads_text
from yoke_core.domain.merge_queue_landing_notice import resolve_lane_recipient
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
    requirement_ids: tuple[int, ...],
) -> str:
    """Keep the hook notice inline; the command help owns recovery."""
    failed = ", ".join(f"#{value}" for value in requirement_ids)
    return (
        f"Deployment run {run_id} stage {stage!r} has failed item QA "
        f"requirement(s) {failed} for {item_ref}; recovery: `yoke qa plan run --help`."
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
    recipient, _, _ = resolve_lane_recipient(
        conn, item_id=item_id, project_id=project_id
    )
    placeholders = ",".join("%s" for _ in requirement_ids)
    verdicts = conn.execute(
        "SELECT qa_requirement_id,MAX(id) FROM qa_runs "
        f"WHERE qa_requirement_id IN ({placeholders}) GROUP BY qa_requirement_id",
        requirement_ids,
    ).fetchall()
    latest_by_requirement = {int(row[0]): int(row[1]) for row in verdicts}
    if recipient:
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
                requirement_ids=requirement_ids,
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
