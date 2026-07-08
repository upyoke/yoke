"""Schema initialization and seed data for deployment flows.

Owns the ``deployment_flows`` table DDL, idempotent column migrations,
the seed flows, and the ``item_progress_view`` view that joins items,
flows, deployment runs, and QA status into a single operator-facing
projection.
"""
from __future__ import annotations

import json

from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.schema_common import (
    _add_column_if_not_exists,
    _table_exists,
)
from yoke_core.domain.deployment_flow_seed_stage import ensure_seed_metadata, ensure_seed_stage

# Seed flows
_SEED_FLOWS = [
    {
        "id": "yoke-internal", "project": "yoke", "name": "Internal",
        "description": "Script/doc changes, no deployment needed",
        "stages": json.dumps([
            {"kind": "migration_apply", "model_name": "primary",
             "lifecycle_phase": "implementing"},
            {"name": "merged", "executor": "auto"},
            {"name": "complete", "executor": "auto"},
        ]),
        "on_failure": "halt", "target_env": None,
        "done_description": "Merged to main",
    },
    {
        "id": "yoke-prod-release", "project": "yoke", "name": "Prod Release",
        "description": "Deploy Yoke core and public installer distribution to prod",
        "stages": json.dumps([
            {"kind": "migration_apply", "model_name": "primary",
             "lifecycle_phase": "implementing"},
            {"name": "merged", "executor": "auto"},
            {"name": "env-activate", "executor": "environment-activate"},
            {"name": "core-deploy", "executor": "core-container-deploy"},
            {"name": "health-check", "executor": "health-check"},
            {"name": "distribution-publish",
             "executor": "github-actions-workflow",
             "workflow": "yoke-distribution-publish.yml",
             "ref": "main",
             "inputs": {"channel": "stable", "target_env": "prod", "source_sha": "{head_sha}"},
             "reconcile_by_head_sha": False,
             "qa_kind": "distribution_publish"},
            {"name": "complete", "executor": "auto"},
        ]),
        "on_failure": "halt", "target_env": "prod",
        "done_description": "Yoke core deployed to prod, health check passed, and installer distribution published",
    },
    {
        "id": "yoke-stage-release", "project": "yoke", "name": "Stage Release",
        "description": "Deploy Yoke core and public installer distribution to stage (stage data is throwaway; no governed migration stage)",
        "stages": json.dumps([
            {"name": "merged", "executor": "auto"},
            {"name": "env-activate", "executor": "environment-activate"},
            {"name": "core-deploy", "executor": "core-container-deploy"},
            {"name": "health-check", "executor": "health-check"},
            {"name": "distribution-publish",
             "executor": "github-actions-workflow",
             "workflow": "yoke-distribution-publish.yml",
             "ref": "stage",
             "inputs": {"channel": "latest", "target_env": "stage", "source_sha": "{head_sha}"},
             "reconcile_by_head_sha": False,
             "qa_kind": "distribution_publish"},
            {"name": "complete", "executor": "auto"},
        ]),
        "on_failure": "halt", "target_env": "stage",
        "done_description": "Yoke core deployed to stage, health check passed, and stage installer distribution published",
    },
    {
        "id": "yoke-ephemeral-deploy", "project": "yoke", "name": "Ephemeral Deploy",
        "description": "Deploy a branch/SHA Yoke core preview environment through the shared ephemeral substrate (unmerged worktree branches; no merged gate)",
        "stages": json.dumps([
            {"name": "ephemeral-deploy", "executor": "ephemeral-deploy"},
            {"name": "complete", "executor": "auto"},
        ]),
        "on_failure": "halt", "target_env": "ephemeral",
        "done_description": "Yoke core preview environment deployed",
    },
    {
        "id": "buzz-prod-release", "project": "buzz", "name": "Prod Release",
        "description": "Push-to-main triggers prod deploy via GitHub Actions with environment protection gate, then smoke test",
        "stages": json.dumps([
            {"kind": "migration_apply", "model_name": "primary",
             "lifecycle_phase": "implementing"},
            {"name": "merged", "executor": "auto"},
            {"name": "prod-deploy", "executor": "github-actions-workflow", "workflow": "buzz-deploy.yml"},
            {"name": "smoke", "executor": "github-actions-workflow", "workflow": "buzz-smoke.yml"},
            {"name": "complete", "executor": "auto"},
        ]),
        "on_failure": "halt", "target_env": "production",
        "done_description": "Deployed to production and smoke checks passed",
    },
    {
        "id": "buzz-prod-hotfix", "project": "buzz", "name": "Prod Hotfix",
        "description": "Manual dispatch of hotfix workflow for direct-to-prod deploy",
        "stages": json.dumps([
            {"kind": "migration_apply", "model_name": "primary",
             "lifecycle_phase": "implementing"},
            {"name": "merged", "executor": "auto"},
            {"name": "production-deploy", "executor": "github-actions-workflow",
             "workflow": "buzz-hotfix.yml", "watch_for": "completed", "on_failure": "halt"},
        ]),
        "on_failure": "halt", "target_env": "production",
        "done_description": "Hotfix deployed to production",
    },
    {
        "id": "buzz-internal", "project": "buzz", "name": "Internal",
        "description": "Doc or config change, no deployment",
        "stages": json.dumps([
            {"name": "merged", "executor": "auto"},
            {"name": "complete", "executor": "auto"},
        ]),
        "on_failure": "halt", "target_env": None,
        "done_description": "Merged to main",
    },
]


def cmd_init(conn) -> str:
    # Create table
    conn.execute("""\
        CREATE TABLE IF NOT EXISTS deployment_flows (
            id TEXT PRIMARY KEY,
            project_id INTEGER NOT NULL REFERENCES projects(id),
            name TEXT NOT NULL,
            description TEXT,
            stages TEXT NOT NULL,
            on_failure TEXT DEFAULT 'halt',
            created_at TEXT NOT NULL,
            UNIQUE(project_id, name)
        )""")

    # Migrations: add columns idempotently. Introspect-then-ALTER (not
    # try/except-swallow): a failed ALTER aborts the whole transaction on
    # Postgres, so a swallowed DuplicateColumn would poison every later
    # statement with InFailedSqlTransaction. ``_add_column_if_not_exists``
    # checks the live column set first and only ALTERs when missing.
    _add_column_if_not_exists(conn, "deployment_flows", "target_env", "TEXT DEFAULT NULL")
    _add_column_if_not_exists(conn, "deployment_flows", "done_description", "TEXT DEFAULT NULL")

    # Add deployment_flow / deploy_stage to items (idempotent).
    # NOTE: SQLite silently drops the inline `REFERENCES` clause on
    # `ALTER TABLE ... ADD COLUMN`; the live `items` schema therefore has
    # no FK on `deployment_flow`. The runtime backstop is the registry
    # validator at `yoke_core.domain.deployment_flow_validator` plus
    # `HC-invalid-item-flows`. A physical FK requires rebuilding `items`.
    _add_column_if_not_exists(
        conn, "items", "deployment_flow", "TEXT REFERENCES deployment_flows(id)"
    )
    _add_column_if_not_exists(conn, "items", "deploy_stage", "TEXT DEFAULT NULL")

    # Seed flows — only for projects that exist in this universe. A fresh
    # universe seeds no project rows, so it gets no flow rows either; the
    # flow definitions converge on installs whose registry carries the
    # matching project (resolved by slug, never by an assumed numeric id).
    project_ids = {
        str(row[0]): int(row[1])
        for row in conn.execute("SELECT slug, id FROM projects").fetchall()
    }
    seeded_flows = [
        flow for flow in _SEED_FLOWS if str(flow["project"]) in project_ids
    ]
    for flow in seeded_flows:
        conn.execute(
            "INSERT INTO deployment_flows "
            "(id, project_id, name, description, stages, on_failure, target_env, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT(id) DO NOTHING",
            (
             flow["id"], project_ids[str(flow["project"])],
             flow["name"], flow["description"],
             flow["stages"], flow["on_failure"], flow.get("target_env"),
             iso8601_now()),
        )

    # Backfill target_env and done_description for existing rows
    backfills = [
        ("target_env", "production", "buzz-prod-release"),
        ("target_env", "production", "buzz-prod-hotfix"),
    ]
    for col, val, fid in backfills:
        conn.execute(
            f"UPDATE deployment_flows SET {col}=%s WHERE id=%s AND {col} IS NULL",
            (val, fid),
        )

    for flow in _SEED_FLOWS:
        if flow.get("done_description"):
            conn.execute(
                "UPDATE deployment_flows SET done_description=%s "
                "WHERE id=%s AND done_description IS NULL",
                (flow["done_description"], flow["id"]),
            )

    # Bootstrap backfill: ensure each flow that ships a
    # ``migration_apply`` stage in the seed actually has it on the live
    # row. Existing rows from before governed-DB-mutation landed need the stage
    # prepended idempotently.  This is the runtime side of §11.4 — the
    # bootstrap exception that installs the contract that governs future
    # migrations on the project.
    for flow in _SEED_FLOWS:
        try:
            seed_stages = json.loads(flow["stages"])
        except (json.JSONDecodeError, TypeError, KeyError):
            continue
        seed_apply = next(
            (s for s in seed_stages
             if isinstance(s, dict) and s.get("kind") == "migration_apply"),
            None,
        )
        if seed_apply is None:
            continue
        row = conn.execute(
            "SELECT stages FROM deployment_flows WHERE id = %s",
            (flow["id"],),
        ).fetchone()
        if row is None:
            continue
        raw_live = row[0] if not hasattr(row, "keys") else row["stages"]
        try:
            live_stages = json.loads(raw_live) if raw_live else []
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(live_stages, list):
            continue
        already_present = any(
            isinstance(s, dict)
            and s.get("kind") == "migration_apply"
            and s.get("model_name") == seed_apply.get("model_name")
            for s in live_stages
        )
        if already_present:
            continue
        merged = [seed_apply] + live_stages
        conn.execute(
            "UPDATE deployment_flows SET stages = %s WHERE id = %s",
            (json.dumps(merged), flow["id"]),
        )

    ensure_seed_stage(
        conn,
        seed_flows=_SEED_FLOWS,
        flow_id="yoke-prod-release",
        stage_name="distribution-publish",
        before_stage="complete",
    )
    ensure_seed_stage(
        conn,
        seed_flows=_SEED_FLOWS,
        flow_id="yoke-stage-release",
        stage_name="distribution-publish",
        before_stage="complete",
    )
    ensure_seed_metadata(
        conn,
        seed_flows=_SEED_FLOWS,
        flow_ids=("yoke-prod-release", "yoke-stage-release"),
    )

    conn.commit()

    # Create item_progress_view
    create_or_replace_item_progress_view(conn)

    return "Deployment flows initialized"


def create_or_replace_item_progress_view(conn) -> None:
    """Create or replace ``item_progress_view``.

    Drops and recreates the view from the canonical fresh-schema
    definition so existing installs converge on the same column shape
    as new initializations.
    """
    has_runs = _table_exists(conn, "deployment_runs")
    has_qa_reqs = _table_exists(conn, "qa_requirements")

    conn.execute("DROP VIEW IF EXISTS item_progress_view")

    if has_runs:
        stage_progress_expr = (
            "(SELECT COUNT(*) FROM "
            "jsonb_array_elements(NULLIF(df.stages, '')::jsonb) je "
            "WHERE je->>'name' <= dr.current_stage)"
            " || '/' || "
            "(SELECT COUNT(*) FROM "
            "jsonb_array_elements(NULLIF(df.stages, '')::jsonb))"
        )
        smoke_expr = (
            "(SELECT qr.id || ':' || COALESCE("
            "(SELECT qrun.verdict FROM qa_runs qrun "
            "WHERE qrun.qa_requirement_id = qr.id "
            "ORDER BY qrun.created_at DESC LIMIT 1), 'pending') "
            "FROM qa_requirements qr "
            "WHERE qr.deployment_run_id = dr.id "
            "AND qr.qa_kind = 'smoke' AND qr.qa_phase = 'post_deploy' "
            "LIMIT 1) AS smoke_qa_status"
            if has_qa_reqs
            else "NULL AS smoke_qa_status"
        )
        conn.execute(f"""\
            CREATE VIEW item_progress_view AS
            SELECT
                i.id AS item_id, i.status,
                df.name AS flow_name, dr.id AS run_id, dr.current_stage,
                COALESCE(dr.target_env, df.target_env) AS target_env,
                CASE WHEN dr.id IS NOT NULL AND df.stages IS NOT NULL THEN
                    {stage_progress_expr}
                ELSE NULL END AS stage_progress,
                df.done_description,
                (SELECT drq.check_name || ':' || drq.status
                 FROM deployment_run_qa drq WHERE drq.run_id = dr.id
                 ORDER BY drq.updated_at DESC LIMIT 1) AS qa_summary,
                CASE
                    WHEN dr.status = 'failed' THEN
                        dr.current_stage || ': ' || COALESCE(
                            (SELECT drq.check_name FROM deployment_run_qa drq
                             WHERE drq.run_id = dr.id AND drq.status = 'failed' LIMIT 1),
                            'stage failed')
                    WHEN EXISTS (SELECT 1 FROM deployment_run_qa drq
                                 WHERE drq.run_id = dr.id AND drq.status = 'failed')
                    THEN dr.current_stage || ': ' ||
                        (SELECT drq.check_name FROM deployment_run_qa drq
                         WHERE drq.run_id = dr.id AND drq.status = 'failed' LIMIT 1)
                    ELSE NULL
                END AS pipeline_blocked_reason,
                {smoke_expr}
            FROM items i
            LEFT JOIN deployment_flows df ON df.id = i.deployment_flow
            LEFT JOIN deployment_run_items dri ON dri.item_id = i.id
            LEFT JOIN deployment_runs dr ON dr.id = dri.run_id
                AND dr.status IN ('created', 'executing')
        """)
    else:
        conn.execute("""\
            CREATE VIEW item_progress_view AS
            SELECT
                i.id AS item_id, i.status,
                df.name AS flow_name,
                NULL AS run_id, NULL AS current_stage,
                df.target_env,
                NULL AS stage_progress, df.done_description,
                NULL AS qa_summary, NULL AS pipeline_blocked_reason,
                NULL AS smoke_qa_status
            FROM items i
            LEFT JOIN deployment_flows df ON df.id = i.deployment_flow
        """)

    conn.commit()
