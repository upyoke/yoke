"""Schema initialization for deployment flows.

Owns the ``deployment_flows`` table DDL, idempotent column migrations,
and the ``item_progress_view`` view that joins items, project-owned flows,
deployment runs, and QA status into a single operator-facing projection.
"""

from __future__ import annotations

from yoke_core.domain.schema_common import (
    _add_column_if_not_exists,
    _table_exists,
)


def _ensure_flow_schema(conn) -> None:
    """Create the flow registry and its strictly additive columns."""
    # The environment reference is a physical FK only when the registry
    # precedes this step (the converge order guarantees it does); minimal
    # fixture databases without a registry keep the column unconstrained,
    # the same stance items.deployment_flow takes.
    environment_ref = (
        "TEXT REFERENCES environments(id)"
        if _table_exists(conn, "environments")
        else "TEXT"
    )
    conn.execute(f"""\
        CREATE TABLE IF NOT EXISTS deployment_flows (
            id TEXT PRIMARY KEY,
            project_id INTEGER NOT NULL REFERENCES projects(id),
            name TEXT NOT NULL,
            description TEXT,
            stages TEXT NOT NULL,
            on_failure TEXT DEFAULT 'halt',
            created_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            target_tier TEXT,
            target_environment_id {environment_ref},
            CONSTRAINT deployment_flows_target_tier_vocabulary
                CHECK (target_tier IS NULL
                       OR target_tier IN ('persistent','ephemeral')),
            CONSTRAINT deployment_flows_target_tier_environment
                CHECK ((target_tier IS NOT NULL
                        AND target_tier = 'persistent')
                       = (target_environment_id IS NOT NULL)),
            UNIQUE(project_id, name)
        )""")

    # Migrations: add columns idempotently. Introspect-then-ALTER (not
    # try/except-swallow): a failed ALTER aborts the whole transaction on
    # Postgres, so a swallowed DuplicateColumn would poison every later
    # statement with InFailedSqlTransaction. ``_add_column_if_not_exists``
    # checks the live column set first and only ALTERs when missing.
    # The tier/environment pair lands additively here; the legacy
    # ``target_env`` label is recoded and dropped by the ordered
    # migration history, which also installs the tier/environment CHECK
    # on pre-existing databases.
    _add_column_if_not_exists(
        conn, "deployment_flows", "target_tier", "TEXT DEFAULT NULL"
    )
    _add_column_if_not_exists(
        conn, "deployment_flows", "target_environment_id", environment_ref,
    )
    _add_column_if_not_exists(
        conn, "deployment_flows", "done_description", "TEXT DEFAULT NULL"
    )
    _add_column_if_not_exists(
        conn, "deployment_flows", "status", "TEXT NOT NULL DEFAULT 'active'"
    )

    # Existing deployment_runs tables predate the typed target pair; the
    # legacy target_env label is recoded and dropped by the ordered
    # migration history. This runs on the converge path before the view
    # below references the pair.
    if _table_exists(conn, "deployment_runs"):
        _add_column_if_not_exists(conn, "deployment_runs", "target_tier", "TEXT")
        _add_column_if_not_exists(
            conn, "deployment_runs", "target_environment_id", environment_ref,
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


def converge_flow_catalog(conn) -> None:
    """Converge the additive flow schema without project-owned definitions.

    Project repositories declare definitions in ``.yoke/deployment-flows.json``
    and materialize them through project refresh. Schema boot never guesses a
    project's delivery topology or rewrites historical definitions.
    """
    _ensure_flow_schema(conn)
    conn.commit()


def cmd_init(conn) -> str:
    _ensure_flow_schema(conn)
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
    # Minimal fixture databases carry flows without the environment
    # registry; the resolved-name projection degrades to the tier label.
    has_envs = _table_exists(conn, "environments")

    conn.execute("DROP VIEW IF EXISTS item_progress_view")

    target_expr = (
        "COALESCE(te.name, df.target_tier)" if has_envs else "df.target_tier"
    )
    flow_env_join = (
        "LEFT JOIN environments te ON te.id = df.target_environment_id"
        if has_envs
        else ""
    )
    env_join = (
        "LEFT JOIN environments te ON te.id = COALESCE("
        "dr.target_environment_id, df.target_environment_id)"
        if has_envs
        else ""
    )

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
                {target_expr} AS target_environment,
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
            {env_join}
        """)
    else:
        conn.execute(f"""\
            CREATE VIEW item_progress_view AS
            SELECT
                i.id AS item_id, i.status,
                df.name AS flow_name,
                NULL AS run_id, NULL AS current_stage,
                {target_expr} AS target_environment,
                NULL AS stage_progress, df.done_description,
                NULL AS qa_summary, NULL AS pipeline_blocked_reason,
                NULL AS smoke_qa_status
            FROM items i
            LEFT JOIN deployment_flows df ON df.id = i.deployment_flow
            {flow_env_join}
        """)

    conn.commit()
