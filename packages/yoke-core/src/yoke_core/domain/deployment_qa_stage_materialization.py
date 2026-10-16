"""Materialize private cases and shared plan groups for deployment QA."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.qa_plan_management import QaPlanError
from yoke_core.domain.schema_read_scope import composition_operation


class QaCasesNotSelectedError(QaPlanError):
    """No cases are selected for this stage subject yet.

    Deliberately its own type, because it is the ONLY materialization
    refusal that describes work an agent has not done rather than a
    definition that is wrong. The default story is that a stage names no
    cases and the responsible agent chooses or creates them, so a caller
    must be able to tell "nobody has selected cases yet" — a durable wait
    that should wake that agent — from an invalid pinned plan, an
    unresolvable target identity, or a permission failure, all of which
    are real stage failures. Collapsing them would either strand the
    agent or dress a broken definition up as patience.
    """


@composition_operation
def materialize_deployment_qa_stage(
    conn: Any,
    *,
    deployment_run_id: str,
    deployment_stage: str,
    deployment_member_item_id: int | None = None,
    agent_plan: str | None = None,
    commit: bool = True,
    replacement_keys: set[str] | None = None,
    replaced_requirement_ids: frozenset[int] = frozenset(),
    replacement_scopes: dict[str, list[dict]] | None = None,
) -> dict[str, Any]:
    """Create each selected plan once for its source and deployed target."""
    from yoke_core.domain.deployment_qa_stage_contract import (
        deployment_qa_stage_subject,
    )
    from yoke_core.domain.deployment_qa_execution_target import (
        deployment_qa_execution_target,
    )
    from yoke_core.domain.deployment_qa_frozen_plan_selection import member_requirements
    from yoke_core.domain.deployment_qa_plan_selection import selected_plans
    from yoke_core.domain.deployment_qa_shared_plans import (
        shared_subject,
        shareable_snapshots,
    )
    from yoke_core.domain.deployment_qa_subject_materialization import (
        materialize_subject,
    )

    subject = deployment_qa_stage_subject(
        conn,
        run_id=deployment_run_id,
        stage_name=deployment_stage,
        member_item_id=deployment_member_item_id,
    )
    target = deployment_qa_execution_target(conn, subject)
    admitted = member_requirements(conn, subject, target=target)
    snapshots = (
        [subject["shared_snapshot"]]
        if subject.get("shared_plan")
        else selected_plans(
            conn,
            subject,
            agent_plan=agent_plan,
            target=target,
            admitted=admitted,
            allow_empty=True,
            replacement_keys=replacement_keys,
            replacement_scopes=replacement_scopes,
        )
    )
    try:
        conn.execute(
            "SELECT id FROM deployment_runs WHERE id=%s FOR UPDATE",
            (deployment_run_id,),
        )
        from yoke_core.domain.deployment_qa_materialization_projection import (
            MaterializationProjection,
        )

        from yoke_core.domain.deployment_qa_snapshot_selection import (
            freeze_selected_plans,
        )

        freeze_selected_plans(conn, subject, snapshots)
        projection = MaterializationProjection(
            conn, deployment_run_id, deployment_stage
        )
        shared = shareable_snapshots(
            conn, subject, target, snapshots, projection=projection
        )
        if not shared:
            result = materialize_subject(
                conn,
                subject=subject,
                target=target,
                admitted=admitted,
                snapshots=snapshots,
                commit=False,
                replaced_requirement_ids=replaced_requirement_ids,
            )
        else:
            results = []
            for snapshot in shared:
                group = shared_subject(subject, target, snapshot)
                results.append(
                    materialize_subject(
                        conn,
                        subject=group,
                        target=deployment_qa_execution_target(conn, group),
                        admitted=[],
                        snapshots=[snapshot],
                        commit=False,
                        replaced_requirement_ids=replaced_requirement_ids,
                    )
                )
                from yoke_core.domain.deployment_qa_shared_duplicates import (
                    retire_member_copies,
                )

                retire_member_copies(
                    conn,
                    group,
                    deployment_qa_execution_target(conn, group),
                    [
                        *results[-1]["created_requirement_ids"],
                        *results[-1]["existing_requirement_ids"],
                    ],
                    projection=projection,
                )
            private = [r for r in admitted if r.get("plan_id") is None]
            private_snapshots = [
                snapshot for snapshot in snapshots if snapshot not in shared
            ]
            from yoke_core.domain.deployment_qa_shared_corrections import (
                correction_subjects,
            )

            corrections, private_snapshots = correction_subjects(
                conn,
                subject,
                private_snapshots,
                replaced_requirement_ids,
            )
            for group, snapshot in corrections:
                results.append(
                    materialize_subject(
                        conn,
                        subject=group,
                        target=deployment_qa_execution_target(conn, group),
                        admitted=[],
                        snapshots=[snapshot],
                        commit=False,
                        replaced_requirement_ids=replaced_requirement_ids,
                    )
                )
            if private or private_snapshots:
                results.append(
                    materialize_subject(
                        conn,
                        subject=subject,
                        target=target,
                        admitted=private,
                        snapshots=private_snapshots,
                        commit=False,
                        replaced_requirement_ids=replaced_requirement_ids,
                    )
                )
            result = {
                **results[0],
                "deployment_member_item_id": deployment_member_item_id,
                "created_requirement_ids": [
                    r for part in results for r in part["created_requirement_ids"]
                ],
                "existing_requirement_ids": [
                    r for part in results for r in part["existing_requirement_ids"]
                ],
            }
        if commit:
            conn.commit()
        return result
    except Exception:
        if commit:
            conn.rollback()
        raise


__all__ = ["QaCasesNotSelectedError", "materialize_deployment_qa_stage"]
