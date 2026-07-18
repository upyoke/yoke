"""Schema initialization and seed data for deployment flows.

Owns the ``deployment_flows`` table DDL, idempotent column migrations,
the seed flows, and the ``item_progress_view`` view that joins items,
flows, deployment runs, and QA status into a single operator-facing
projection.
"""
from __future__ import annotations

import json

from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.deployment_flow_seed_data import SEED_FLOWS as _SEED_FLOWS
from yoke_core.domain.flow_supersession import (
    converge_builtin_flow_supersessions,
)
from yoke_core.domain.schema_common import (
    _add_column_if_not_exists,
    _table_exists,
)
from yoke_core.domain.deployment_flow_state import FLOW_STATUS_ACTIVE


def _ensure_flow_schema(conn) -> None:
    """Create the flow registry and its strictly additive columns."""
    conn.execute("""\
        CREATE TABLE IF NOT EXISTS deployment_flows (
            id TEXT PRIMARY KEY,
            project_id INTEGER NOT NULL REFERENCES projects(id),
            name TEXT NOT NULL,
            description TEXT,
            stages TEXT NOT NULL,
            on_failure TEXT DEFAULT 'halt',
            created_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            UNIQUE(project_id, name)
        )""")

    # Migrations: add columns idempotently. Introspect-then-ALTER (not
    # try/except-swallow): a failed ALTER aborts the whole transaction on
    # Postgres, so a swallowed DuplicateColumn would poison every later
    # statement with InFailedSqlTransaction. ``_add_column_if_not_exists``
    # checks the live column set first and only ALTERs when missing.
    _add_column_if_not_exists(conn, "deployment_flows", "target_env", "TEXT DEFAULT NULL")
    _add_column_if_not_exists(conn, "deployment_flows", "done_description", "TEXT DEFAULT NULL")
    _add_column_if_not_exists(
        conn, "deployment_flows", "status", "TEXT NOT NULL DEFAULT 'active'"
    )

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


def _seed_missing_flow_definitions(conn) -> None:
    """Insert code-owned flow definitions that are absent from a universe.

    Existing rows are deliberately left untouched: a disabled definition must
    stay disabled, historical runs must keep resolving their original flow,
    and project-authored customizations are not silently rewritten on boot.
    """

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
            "(id, project_id, name, description, stages, on_failure, target_env, "
            "done_description, status, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT(id) DO NOTHING",
            (
             flow["id"], project_ids[str(flow["project"])],
             flow["name"], flow["description"],
             flow["stages"], flow["on_failure"], flow.get("target_env"),
             flow.get("done_description"), flow.get("status", "active"),
             iso8601_now()),
        )


def converge_flow_catalog(conn) -> None:
    """Converge additive flow schema and code-owned flow definitions.

    This is the existing-universe boot path. It is safe to run repeatedly,
    never deletes or rewrites a predecessor, and never changes a deployment
    run. Exact code-owned predecessors may be disabled once every binding is
    terminal; modified definitions stay untouched.
    """
    _ensure_flow_schema(conn)
    _seed_missing_flow_definitions(conn)
    converge_builtin_flow_supersessions(conn)
    conn.commit()


def cmd_init(conn) -> str:
    _ensure_flow_schema(conn)
    _seed_missing_flow_definitions(conn)

    for flow in _SEED_FLOWS:
        if flow.get("done_description"):
            conn.execute(
                "UPDATE deployment_flows SET done_description=%s "
                "WHERE id=%s AND done_description IS NULL",
                (flow["done_description"], flow["id"]),
            )

    # Ensure a seed's governed migration stage is present on its live row.
    for flow in _SEED_FLOWS:
        if flow["status"] != FLOW_STATUS_ACTIVE:
            continue
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

    converge_builtin_flow_supersessions(conn)
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
