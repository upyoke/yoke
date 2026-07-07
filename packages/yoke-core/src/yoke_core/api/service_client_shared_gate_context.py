"""Item-state loading, schema introspection, and gate-context assembly.

Owns the read-only DB inspection used by the mutation gates: hydrating
an :class:`yoke_core.domain.mutations.ItemState` from the ``items``
row, probing whether optional tables exist, resolving the set of valid
deployment environments for a project (``environments``/``sites`` →
``deployment_flows.target_env`` → ``project_capabilities`` cascade),
and packaging the result into the
:class:`yoke_core.domain.mutations.GateContext` consumed by
``prepare_update`` / ``prepare_approval``.
"""

from __future__ import annotations

import json
from typing import Any

from yoke_core.domain import mutations
from yoke_core.domain.project_identity import resolve_project
from yoke_core.domain.schema_common import _table_exists as _schema_table_exists


def _load_item_state(conn: Any, item_id: int) -> mutations.ItemState | None:
    """Load an ItemState from the DB, or return None if not found."""
    row = conn.execute(
        "SELECT i.*, p.slug AS project FROM items i "
        "JOIN projects p ON p.id = i.project_id "
        "WHERE i.id = %s",
        (item_id,),
    ).fetchone()
    if row is None:
        return None
    d = dict(row)
    return mutations.ItemState(
        id=d["id"],
        title=d["title"],
        item_type=d["type"],
        status=d["status"],
        priority=d["priority"],
        rework_count=d.get("rework_count", 0),
        frozen=bool(d.get("frozen", 0)),
        project=d.get("project"),
        deployment_flow=d.get("deployment_flow"),
        deploy_stage=d.get("deploy_stage"),
        deployed_to=d.get("deployed_to"),
        worktree=d.get("worktree"),
        merged_at=d.get("merged_at"),
    )


def _table_exists(conn: Any, table_name: str) -> bool:
    """Check if a table exists in the DB."""
    return _schema_table_exists(conn, table_name)


def _resolve_deploy_envs(conn: Any, project: str) -> list[str] | None:
    """Resolve valid deployment environments for a project.

    Mirrors the resolution logic in yoke_core.domain.projects resolve-deploy-envs:
    1. Query environments/sites tables (if they exist)
    2. UNION with deployment_flows.target_env (if table exists)
    3. Fall back to project_capabilities deployment_environments config

    No config-file fallback — DB is the sole source of truth.
    Returns a list of environment names, or None if no resolution was possible.
    """
    envs: set[str] = set()
    ident = resolve_project(conn, project)
    assert ident is not None

    if _table_exists(conn, "environments") and _table_exists(conn, "sites"):
        rows = conn.execute(
            """SELECT DISTINCT e.name AS env_name
               FROM environments e
               JOIN sites s ON s.id = e.site
               WHERE s.project_id = %s""",
            (ident.id,),
        ).fetchall()
        for r in rows:
            if r["env_name"]:
                envs.add(r["env_name"])

    if _table_exists(conn, "deployment_flows"):
        rows = conn.execute(
            """SELECT DISTINCT target_env AS env_name
               FROM deployment_flows
               WHERE project_id = %s
               AND target_env IS NOT NULL
               AND target_env <> ''""",
            (ident.id,),
        ).fetchall()
        for r in rows:
            if r["env_name"]:
                envs.add(r["env_name"])

    if envs:
        return sorted(envs)

    if not _table_exists(conn, "project_capabilities"):
        cap_row = None
    else:
        cap_row = conn.execute(
            "SELECT COALESCE(settings, '{}') AS config FROM project_capabilities "
            "WHERE project_id = %s AND type = 'deployment_environments'",
            (ident.id,),
        ).fetchone()
    if cap_row:
        try:
            env_config = json.loads(cap_row["config"])
            cap_envs = env_config.get("environments", [])
            if cap_envs:
                return sorted(cap_envs)
        except (json.JSONDecodeError, TypeError):
            pass

    return None


def _load_gate_context(
    conn: Any,
    item_dict: dict,
    target_status: str | None = None,
    *,
    deployment_flow_value: str | None = None,
    deployed_to_value: str | None = None,
    done_nonce_verified: bool = False,
    force: bool = False,
    qa_bypass: bool = False,
) -> mutations.GateContext:
    """Build a GateContext from the DB for the given item.

    Mirrors the gate-loading logic in main.py's update_item endpoint.
    """
    gate = mutations.GateContext(
        done_nonce_verified=done_nonce_verified,
        force=force,
        qa_bypass=qa_bypass,
    )

    if target_status is not None:
        if item_dict["type"] == "epic":
            task_count_row = conn.execute(
                "SELECT COUNT(*) as cnt FROM epic_tasks WHERE epic_id = %s",
                (item_dict["id"],),
            ).fetchone()
            gate.epic_task_count = task_count_row["cnt"] if task_count_row else 0

        gate.has_merged_at = bool(item_dict.get("merged_at"))

        qa_req_row = conn.execute(
            "SELECT COUNT(*) as cnt FROM qa_requirements WHERE item_id = %s",
            (item_dict["id"],),
        ).fetchone()
        gate.qa_requirement_count = qa_req_row["cnt"] if qa_req_row else 0

        if gate.qa_requirement_count > 0:
            unsatisfied_val = conn.execute(
                """SELECT COUNT(*) as cnt FROM qa_requirements qr
                   WHERE qr.item_id = %s AND qr.qa_phase IN ('validation','verification')
                   AND qr.success_policy = 'blocking'
                   AND NOT EXISTS (
                       SELECT 1 FROM qa_runs qrun
                       WHERE qrun.qa_requirement_id = qr.id
                       AND qrun.verdict IN ('pass', 'waiver')
                   )""",
                (item_dict["id"],),
            ).fetchone()
            gate.unsatisfied_verification_blocking = unsatisfied_val["cnt"] if unsatisfied_val else 0

            unsatisfied_all = conn.execute(
                """SELECT COUNT(*) as cnt FROM qa_requirements qr
                   WHERE qr.item_id = %s AND qr.success_policy = 'blocking'
                   AND NOT EXISTS (
                       SELECT 1 FROM qa_runs qrun
                       WHERE qrun.qa_requirement_id = qr.id
                       AND qrun.verdict IN ('pass', 'waiver')
                   )""",
                (item_dict["id"],),
            ).fetchone()
            gate.unsatisfied_all_blocking = unsatisfied_all["cnt"] if unsatisfied_all else 0

    if deployment_flow_value:
        from yoke_core.domain.deployment_flow_validator import (
            validate_and_lookup_flow_project,
        )

        flow_project, _flow_err = validate_and_lookup_flow_project(
            conn, deployment_flow_value, item_dict.get("project")
        )
        # Callers that accept raw deployment_flow input reject unregistered
        # ids before this helper populates same-project gate context.
        gate.flow_project = flow_project

    if deployed_to_value:
        project = item_dict.get("project") or "yoke"
        resolved_envs = _resolve_deploy_envs(conn, project)
        gate.valid_deploy_envs = resolved_envs if resolved_envs is not None else []

    return gate
