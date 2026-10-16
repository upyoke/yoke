"""Current and frozen definitions for a release member's visible QA."""

import json
from collections import defaultdict

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.deployment_requirement_snapshots import _plan_snapshot
from yoke_core.domain.qa_plan_attachment_reads import live_item_attachment_sql
from yoke_core.domain.qa_plan_case_targets import case_target_envs
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
    """Set-read source rows and live attachments, without their execution history."""
    markers = ",".join("%s" for _ in item_ids)
    sources, plans = defaultdict(list), defaultdict(list)
    suppressed = defaultdict(set)
    if not item_ids:
        return sources, plans
    rows = query_rows(
        conn,
        "SELECT q.id,q.item_id,q.qa_kind,q.qa_phase,q.target_env,q.plan_id,q.plan_case_key,"
        "q.host_baseline,q.method_id,q.method_name,q.instructions,q.execution_target_json,"
        "q.method_config,q.expected_outcome,p.project_id AS plan_project_id,"
        "q.waived_at,q.waiver_rationale,q.retracted_at,q.superseded_by_requirement_id "
        "FROM qa_requirements q LEFT JOIN qa_plans p ON p.id=q.plan_id "
        f"WHERE q.item_id IN ({markers}) AND q.deployment_run_id IS NULL "
        "AND q.qa_phase='post_deploy' "
        "AND NOT EXISTS (SELECT 1 FROM qa_plan_item_attachments a "
        "WHERE a.item_id=q.item_id AND a.plan_id=q.plan_id "
        "AND a.qa_phase='post_deploy' AND a.retracted_at IS NOT NULL) ORDER BY q.id",
        tuple(item_ids),
    )
    for row in rows:
        item = int(row["item_id"])
        if row["retracted_at"] or row["superseded_by_requirement_id"]:
            suppressed[item].add(identity(dict(row)))
        else:
            sources[item].append(dict(row))
    attachments = query_rows(
        conn,
        "SELECT a.item_id,a.plan_id,p.project_id FROM qa_plan_item_attachments a "
        "JOIN qa_plans p ON p.id=a.plan_id "
        f"WHERE a.item_id IN ({markers}) AND a.qa_phase='post_deploy' "
        f"AND {live_item_attachment_sql(conn, 'a')} AND p.retired_at IS NULL",
        tuple(item_ids),
    )
    source_plans = {
        (item, int(row["plan_id"]), int(row["plan_project_id"]))
        for item, rows in sources.items()
        for row in rows
        if row.get("plan_id") is not None
    }
    attachments = [
        *attachments,
        *(
            {"item_id": item, "plan_id": plan, "project_id": project}
            for item, plan, project in sorted(source_plans)
        ),
    ]
    snapshots = {}
    for row in attachments:
        plan_id = int(row["plan_id"])
        if plan_id not in snapshots:
            snapshots[plan_id] = _plan_snapshot(
                conn, plan_id, project_id=int(row["project_id"]), lock_plan=False
            )
        plans[int(row["item_id"])].append(
            {
                **snapshots[plan_id],
                "excluded_identities": suppressed[int(row["item_id"])],
            }
        )
    return sources, plans


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


def definitions(sources, plans, *, environments, environment_names, dynamic):
    """One definition per source identity or plan/case/baseline variant."""
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
    for snapshot in plans:
        if (snapshot.get("attachment") or {}).get(
            "qa_phase", "post_deploy"
        ) != "post_deploy":
            continue
        plan = snapshot["plan"]
        default = environments.get(plan.get("target_environment_id"), "")
        for case in snapshot.get("cases") or []:
            names = case_target_envs(case) or ([default] if default else [])
            if names and not set(names).intersection(environment_names):
                continue
            if not environment_names and not dynamic:
                continue
            baselines = decoded(case.get("host_baselines"), []) or [None]
            destinations = sorted(
                set(names).intersection(environment_names)
                if names
                else environment_names
            )
            for destination in destinations:
                for baseline in baselines:
                    row = {
                        **case,
                        "plan_id": plan["id"],
                        "plan": plan.get("slug"),
                        "host_baseline": baseline,
                        "qa_phase": "post_deploy",
                        "target_env": destination,
                        "plan_source_revision": plan.get("source_revision"),
                    }
                    key = identity(row)
                    excluded = snapshot.get("excluded_identities", ())
                    if key in result or (
                        key not in excluded and (*key[:-1], "") not in excluded
                    ):
                        source = result.get(key, {})
                        result[key] = {
                            **source,
                            **row,
                            "source_requirement_id": source.get(
                                "source_requirement_id"
                            ),
                        }
                        for field in ("waived_at", "waiver_rationale"):
                            if source.get(field):
                                result[key][field] = source[field]
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
