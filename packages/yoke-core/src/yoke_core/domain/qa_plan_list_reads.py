"""Set-based QA plan pages with explicit full-detail reads."""

from __future__ import annotations

from collections import defaultdict
import json
from typing import Any

from yoke_contracts.qa_case_starting_state import stored_fan_out
from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_rows
from yoke_contracts.timestamps import format_instant
from yoke_core.domain.project_identity import resolve_project
from yoke_core.domain.qa_execution_proof import qa_run_outcome
from yoke_core.domain.qa_latest_execution import latest_execution_sql
from yoke_core.domain.qa_method_definitions import method_presentations
from yoke_core.domain.qa_obligation_settlement import (
    unanswered_attempt_sql,
    unretracted_requirement_sql,
)


DEFAULT_PLAN_LIMIT = 25


def _json(raw: Any) -> Any:
    return json.loads(raw) if isinstance(raw, str) else raw or []


def list_plans(
    conn: Any,
    *,
    project: str | None = None,
    limit: int | None = None,
    offset: int = 0,
    full: bool = False,
    include_retired: bool = False,
) -> list[dict]:
    """Read one stable page; full=True adds detail but never lifts the page.

    Retired plans are skipped unless ``include_retired``; every row names its
    retirement either way, so a retired row is never mistaken for an active one.
    """
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    params: tuple = ()
    where = "TRUE" if include_retired else "p.retired_at IS NULL"
    if project is not None:
        identity = resolve_project(conn, project, required=False)
        if identity is None:
            raise LookupError(f"project {project!r} not found")
        where += f" AND p.project_id={marker}"
        params = (int(identity.id),)
    page_limit = limit if limit is not None else DEFAULT_PLAN_LIMIT
    if offset < 0 or page_limit < 1:
        raise ValueError(
            "plan page requires a positive --limit and nonnegative --offset"
        )
    params += (page_limit, offset)
    rows = query_rows(
        conn,
        "SELECT p.*, pr.slug AS project, pr.id AS project_id, pr.slug AS project_slug, "
        "pr.name AS project_name, pr.org_id AS plan_org_id, pr.id AS plan_project_id, "
        "pr.slug AS plan_project_slug, o.id AS tenant_id, o.slug AS tenant_slug, "
        "o.name AS tenant_name, owner.id AS owner_project_id, owner.org_id AS owner_org_id, "
        "s.name AS site_name, e.id AS environment_id, e.name AS environment_name, "
        "e.url, e.settings, s.name || '/' || e.name AS target_environment "
        "FROM qa_plans p JOIN projects pr ON pr.id=p.project_id "
        "JOIN organizations o ON o.id=pr.org_id LEFT JOIN environments e ON e.id=p.target_environment_id "
        "LEFT JOIN sites s ON s.id=e.site LEFT JOIN projects owner ON owner.id=s.project_id "
        f"WHERE {where} ORDER BY pr.slug, p.slug, p.id LIMIT {marker} OFFSET {marker}",
        params,
    )
    if not rows:
        return []
    ids = tuple(int(row["id"]) for row in rows)
    markers = ",".join(marker for _ in ids)
    cases_by_plan: dict[int, list[dict]] = defaultdict(list)
    cases = query_rows(
        conn,
        "SELECT c.plan_id, c.method_id, c.method_config, c.host_baselines, c.starting_state, "
        "c.target_envs, m.display_icon, m.display_order, m.display_group "
        "FROM qa_plan_cases c JOIN qa_methods m ON m.id=c.method_id "
        f"WHERE c.plan_id IN ({markers}) ORDER BY c.plan_id, c.position",
        ids,
    )
    for raw in cases:
        case = dict(raw)
        case["host_baselines"] = _json(case["host_baselines"])
        cases_by_plan[int(case["plan_id"])].append(case)
    # The plan_id index bounds this to the page's own requirements and the
    # lateral LIMIT 1 reads each one's newest run through its index, so the
    # cost follows the page rather than the whole requirement and run history.
    outcomes = query_rows(
        conn,
        "SELECT DISTINCT ON (q.plan_id) q.plan_id, q.id, q.waived_at, r.verdict, "
        "r.verdict_reason, r.case_outcome, "
        "COALESCE(r.completed_at, r.created_at, q.created_at) AS happened_at "
        f"FROM qa_requirements q LEFT JOIN LATERAL ({latest_execution_sql('q.id')}) r ON TRUE "
        f"WHERE q.plan_id IN ({markers}) AND {unretracted_requirement_sql(conn, 'q')} "
        f"AND {unanswered_attempt_sql(conn, 'q')} "
        "ORDER BY q.plan_id, happened_at DESC, q.id DESC",
        ids,
    )
    last_by_plan = {int(row["plan_id"]): row for row in outcomes}
    attachments: dict[int, list[dict]] = {}
    if full:
        from yoke_core.domain.qa_plan_attachment_reads import plan_attachments_by_plan

        attachments = plan_attachments_by_plan(conn, list(ids))
    result = []
    for raw in rows:
        row = dict(raw)
        plan_id = int(row["id"])
        cases = cases_by_plan[plan_id]
        latest = last_by_plan.get(plan_id)
        output = {
            "id": plan_id,
            "project": str(row["project"]),
            "slug": str(row["slug"]),
            "name": str(row["name"]),
            "target_environment": row["target_environment"],
            "retired_at": format_instant(row["retired_at"])
            if row["retired_at"] is not None
            else None,
            "retirement_reason": row.get("retirement_reason"),
            "case_count": len(cases),
            "materialized_requirement_count": sum(
                len(hosts) * max(1, len(_json(case["target_envs"])))
                for case, hosts in zip(cases, stored_fan_out(cases))
            ),
            "method_ids": list(dict.fromkeys(str(case["method_id"]) for case in cases)),
            "method_presentations": method_presentations(cases),
            "last_outcome": qa_run_outcome(latest) if latest is not None else None,
            "last_at": latest["happened_at"] if latest is not None else None,
        }
        if full:
            output.update(
                description=str(row["description"]),
                attachments=attachments.get(plan_id, []),
                execution_target=_target(row, cases),
                last_verdict_reason=latest["verdict_reason"]
                if latest is not None
                else None,
            )
        result.append(output)
    return result


def _target(identity: dict, cases: list[dict]) -> dict | None:
    from yoke_core.domain.qa_project_execution_target import (
        project_execution_target_from_cases,
    )
    from yoke_core.domain.qa_environment_execution_target import (
        environment_target_snapshot,
    )
    from yoke_core.domain.qa_hosted_runtime_identity import _environment_allowed
    from yoke_core.domain.qa_execution_environment_target import QaExecutionTargetError

    if not identity["target_environment_id"]:
        return project_execution_target_from_cases(
            plan_id=int(identity["id"]),
            identity=identity,
            cases=cases,
            allow_unbound=True,
        )
    if identity["environment_id"] is None or not _environment_allowed(identity):
        raise QaExecutionTargetError(
            "QA plan environment is unavailable or unauthorized; select an environment "
            "owned by the plan project or declare its hosted-runtime consumer with "
            "yoke projects environment-settings merge"
        )
    return environment_target_snapshot(identity)
