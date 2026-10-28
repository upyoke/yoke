"""Current and frozen definitions for a release member's visible item cases.

Post-deploy plans are not an item's cases: each runs once per release as a
plan group under Run QA, so neither an attachment nor an old plan copy adds a
definition here.
"""

import json
from collections import defaultdict

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.deployment_member_post_deploy_admission import (
    requirement_target_environment,
)


def decoded(raw, default):
    return (
        raw
        if isinstance(raw, (dict, list))
        else json.loads(str(raw or json.dumps(default)))
    )


def current_sources(conn, item_ids):
    """Set-read each item's live post-deploy item cases, without execution history."""
    sources = defaultdict(list)
    if not item_ids:
        return sources
    markers = ",".join("%s" for _ in item_ids)
    rows = query_rows(
        conn,
        "SELECT q.id,q.item_id,q.qa_kind,q.qa_phase,q.target_env,q.plan_id,q.plan_case_key,"
        "q.host_baseline,q.method_id,q.method_name,q.instructions,q.execution_target_json,"
        "q.method_config,q.expected_outcome,"
        "q.waived_at,q.waiver_rationale,q.retracted_at,q.superseded_by_requirement_id "
        "FROM qa_requirements q "
        f"WHERE q.item_id IN ({markers}) AND q.deployment_run_id IS NULL "
        "AND q.qa_phase='post_deploy' AND q.plan_id IS NULL ORDER BY q.id",
        tuple(item_ids),
    )
    for row in rows:
        if not (row["retracted_at"] or row["superseded_by_requirement_id"]):
            sources[int(row["item_id"])].append(dict(row))
    return sources


def stage_environments(conn, stages, run):
    """Only declared QA destinations; unresolved preview targets stay explicit."""
    names = set()
    unresolved = []
    for stage in decoded(stages, []):
        if stage.get("stage_kind") != "qa" or stage.get("scope") != "item":
            continue
        target = stage.get("target") or {}
        if target.get("kind") == "persistent_environment":
            names.add(str(target["environment"]))
        else:
            from yoke_core.domain.deployment_stage_receipts import (
                deployment_stage_receipt_for_qa,
            )

            try:
                receipt = deployment_stage_receipt_for_qa(
                    conn,
                    run_id=str(run["id"]),
                    source_stage=str(target.get("source_stage") or ""),
                    expected_target_kind=str(target.get("kind") or ""),
                    expected_target_name=None,
                    expected_release_lineage=str(run.get("release_lineage") or ""),
                    expected_artifact_identity=run.get("artifact_identity"),
                )
                names.add(str(receipt["target_name"]))
            except ValueError as exc:
                unresolved.append(str(exc))
    return (
        names,
        bool(unresolved),
        ("item_qa_target_pending: " + "; ".join(unresolved) if unresolved else None),
    )


def definitions(sources, *, environment_names, dynamic):
    """One definition per source identity; a frozen plan case per environment."""
    result = {}
    for source in sources:
        row = dict(source)
        declared = requirement_target_environment(
            row.get("target_env"), row.get("execution_target_json")
        )
        if declared and declared not in environment_names:
            continue
        if not environment_names and not dynamic:
            continue
        row["source_requirement_id"] = row["id"]
        row["case_key"] = row.get("plan_case_key")
        row["target_env"] = declared
        if row.get("plan_id") is not None and not declared:
            for environment in sorted(environment_names):
                variant = {**row, "target_env": environment}
                result[identity(variant)] = variant
        else:
            result[identity(row)] = row
    return result


def identity(row):
    if row.get("plan_id") is not None:
        from yoke_core.domain.qa_deployment_case_content_refresh import base_case_key

        return (
            "plan",
            int(row["plan_id"]),
            base_case_key(row.get("case_key") or row.get("plan_case_key") or ""),
            row.get("host_baseline"),
            requirement_target_environment(
                row.get("target_env"), row.get("execution_target_json")
            ),
        )
    from yoke_core.domain.deployment_qa_admission_materialization import (
        admitted_source_requirement_id,
    )

    return (
        "source",
        row.get("source_requirement_id")
        or admitted_source_requirement_id(
            row.get("case_key") or row.get("plan_case_key")
        )
        or row.get("id"),
    )
