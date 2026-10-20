"""Keep declared corrections on the shared obligation they answer."""

import json

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.qa_execution_environment_target import target_digest
from yoke_core.domain.qa_plan_management import QaPlanError


def correction_subjects(conn, subject, snapshots, replaced_ids, *, projection):
    """A correction inherits the failed group's identity, including its plan source.

    The groups come from ``projection``, read with the run's other facts.
    """
    if not replaced_ids:
        return [], snapshots
    rows = query_rows(
        conn,
        "SELECT deployment_run_id,deployment_stage,deployment_member_item_id,"
        "execution_target_json,plan_case_key FROM qa_requirements "
        f"WHERE id IN ({','.join('%s' for _ in replaced_ids)})",
        tuple(sorted(replaced_ids)),
    )
    stage = subject["stage"]["name"]
    groups = {}
    for row in rows:
        target = json.loads(str(row["execution_target_json"] or "{}"))
        if not (target.get("deployment") or {}).get("shared_plan"):
            continue
        digest = target_digest(target)
        if digest not in projection.digests(stage, subject["member_item_id"]):
            raise QaPlanError(
                "shared_plan_correction_scope: this member does not attach the failed group; select an attaching --member"
            )
        group, keys = groups.setdefault(
            digest,
            (_attached_group(projection, row["deployment_stage"], target), set()),
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


def _attached_group(projection, stage, target):
    """The first attaching member's group for this exact frozen target."""
    from yoke_core.domain.qa_execution_environment_target import canonical_target

    canonical = canonical_target(target)
    for groups in projection.stage_groups(stage).values():
        for group in groups if not isinstance(groups, Exception) else ():
            if group.same_project and group.canonical == canonical:
                return group.subject
    raise ValueError(
        f"shared_plan_subject_unresolved: no member of run {projection.run_id} stage "
        f"{stage} attaches the failed group; restore its plan attachment and current "
        "producer receipt"
    )
