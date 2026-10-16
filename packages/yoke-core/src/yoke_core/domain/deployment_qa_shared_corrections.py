"""Keep refreshes and declared corrections on the shared obligation they answer."""

from functools import wraps
import json

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.deployment_qa_shared_plans import (
    execution_subject,
    member_plan_subjects,
    member_group_digests,
)
from yoke_core.domain.deployment_qa_execution_target import (
    deployment_qa_execution_target,
)
from yoke_core.domain.qa_execution_environment_target import target_digest
from yoke_core.domain.qa_plan_management import QaPlanError


def correction_subjects(conn, subject, snapshots, replaced_ids):
    """A correction inherits the failed group's identity, including its plan source."""
    if not replaced_ids:
        return [], snapshots
    rows = query_rows(
        conn,
        "SELECT deployment_run_id,deployment_stage,deployment_member_item_id,"
        "execution_target_json,plan_case_key FROM qa_requirements "
        f"WHERE id IN ({','.join('%s' for _ in replaced_ids)})",
        tuple(sorted(replaced_ids)),
    )
    groups = {}
    for row in rows:
        target = json.loads(str(row["execution_target_json"] or "{}"))
        if not (target.get("deployment") or {}).get("shared_plan"):
            continue
        digest = target_digest(target)
        if digest not in member_group_digests(
            conn, subject["id"], subject["stage"]["name"], subject["member_item_id"]
        ):
            raise QaPlanError(
                "shared_plan_correction_scope: this member does not attach the failed group; select an attaching --member"
            )
        group, keys = groups.setdefault(
            digest,
            (execution_subject(conn, {**row, "execution_target": target}), set()),
        )
        from yoke_core.domain.qa_deployment_case_content_refresh import base_case_key

        keys.add(base_case_key(row["plan_case_key"]))
    routed, private = [], []
    for snapshot in snapshots:
        used = set()
        for group, keys in groups.values():
            cases = [case for case in snapshot["cases"] if case["case_key"] in keys]
            if cases:
                routed.append((group, {**snapshot, "cases": cases}))
                used.update(case["case_key"] for case in cases)
        rest = [case for case in snapshot["cases"] if case["case_key"] not in used]
        if rest:
            private.append({**snapshot, "cases": rest})
    return routed, private


def route_shared_refresh(refresh):
    """Refresh each selected shared target independently, once per invocation."""

    @wraps(refresh)
    def routed(conn, **kwargs):
        member = kwargs.get("deployment_member_item_id")
        if member is None:
            return refresh(conn, **kwargs)
        from yoke_core.domain.deployment_qa_stage_contract import (
            deployment_qa_stage_subject,
        )

        subject = deployment_qa_stage_subject(
            conn,
            run_id=kwargs["deployment_run_id"],
            stage_name=kwargs["deployment_stage"],
            member_item_id=member,
        )
        groups = member_plan_subjects(
            conn, subject, deployment_qa_execution_target(conn, subject)
        )
        if not groups:
            return refresh(conn, **kwargs)
        selected = kwargs.get("plan")
        results = []
        try:
            for group in groups:
                plan = group["shared_snapshot"]["plan"]
                if selected is not None and str(selected) not in {
                    str(plan["id"]),
                    str(plan["slug"]),
                }:
                    continue
                results.append(
                    refresh(
                        conn,
                        **{
                            **kwargs,
                            "deployment_member_item_id": None,
                            "_selection_member_item_id": member,
                            "commit": False,
                            "plan": plan["id"],
                            "_execution_target_digest": target_digest(
                                deployment_qa_execution_target(conn, group)
                            ),
                        },
                    )
                )
            own = conn.execute(
                "SELECT 1 FROM qa_requirements WHERE deployment_run_id=%s AND deployment_stage=%s "
                "AND deployment_member_item_id=%s AND plan_id IS NOT NULL LIMIT 1",
                (subject["id"], subject["stage"]["name"], member),
            ).fetchone()
            if own and selected is None:
                results.append(refresh(conn, **{**kwargs, "commit": False}))
            if not results:
                raise QaPlanError(
                    "shared_plan_refresh_selection: selected plan is not attached here; inspect this member's plans"
                )
            if kwargs.get("commit", True):
                conn.commit()
        except Exception:
            if kwargs.get("commit", True):
                conn.rollback()
            raise
        return {
            **results[0],
            "deployment_member_item_id": member,
            **{
                key: sorted({value for result in results for value in result[key]})
                for key in (
                    "plan_ids",
                    "created_requirement_ids",
                    "refreshed_requirement_ids",
                    "waived_requirement_ids",
                )
            },
        }

    return routed
