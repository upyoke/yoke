"""Schema initialization and seed data for deployment flows.

Owns the ``deployment_flows`` table DDL, idempotent column migrations,
the seed flows, and the ``item_progress_view`` view that joins items,
flows, deployment runs, and QA status into a single operator-facing
projection.
"""
from __future__ import annotations

import json
from collections.abc import Mapping

from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.deployment_flow_seed_data import (
    BUILTIN_FLOW_SUPERSESSIONS,
    SEED_FLOWS as _SEED_FLOWS,
)
from yoke_core.domain.lifecycle_enums import ItemStatus
from yoke_core.domain.runs import TERMINAL_RUN_STATUSES
from yoke_core.domain.schema_common import (
    _add_column_if_not_exists,
    _column_exists,
    _table_exists,
)
from yoke_core.domain.deployment_flow_state import FLOW_STATUS_ACTIVE


_FLOW_DEFINITION_FIELDS = (
    "name",
    "description",
    "stages",
    "on_failure",
    "target_env",
    "done_description",
)
_TERMINAL_ITEM_BINDING_STATUSES = frozenset({
    ItemStatus.DONE.value,
    ItemStatus.CANCELLED.value,
    ItemStatus.FAILED.value,
    ItemStatus.STOPPED.value,
})


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


def _flow_definition_row(conn, flow_id: str):
    return conn.execute(
        "SELECT project_id, name, description, stages, on_failure, "
        "target_env, done_description, status "
        "FROM deployment_flows WHERE id=%s",
        (flow_id,),
    ).fetchone()


def _normalized_stages(raw: object) -> object:
    try:
        return json.loads(str(raw))
    except (TypeError, ValueError):
        return raw


def _row_matches_definition(row, definition: Mapping[str, object]) -> bool:
    if row is None:
        return False
    actual = dict(zip(_FLOW_DEFINITION_FIELDS, tuple(row)[1:7]))
    for field in _FLOW_DEFINITION_FIELDS:
        actual_value = actual[field]
        expected_value = definition.get(field)
        if field == "stages":
            actual_value = _normalized_stages(actual_value)
            expected_value = _normalized_stages(expected_value)
        if actual_value != expected_value:
            return False
    return True


def _has_nonterminal_binding(conn, flow_id: str) -> bool:
    if _table_exists(conn, "items") and _column_exists(
        conn, "items", "deployment_flow"
    ):
        item_terminals = sorted(_TERMINAL_ITEM_BINDING_STATUSES)
        placeholders = ", ".join("%s" for _ in item_terminals)
        row = conn.execute(
            "SELECT 1 FROM items WHERE deployment_flow=%s "
            f"AND (status IS NULL OR status NOT IN ({placeholders})) LIMIT 1",
            (flow_id, *item_terminals),
        ).fetchone()
        if row is not None:
            return True
    if _table_exists(conn, "deployment_runs"):
        run_terminals = sorted(TERMINAL_RUN_STATUSES)
        placeholders = ", ".join("%s" for _ in run_terminals)
        row = conn.execute(
            "SELECT 1 FROM deployment_runs WHERE flow=%s "
            f"AND (status IS NULL OR status NOT IN ({placeholders})) LIMIT 1",
            (flow_id, *run_terminals),
        ).fetchone()
        if row is not None:
            return True
    return False


def _repoint_builtin_deploy_default(
    conn, project_id: int, predecessor_id: str, successor_id: str
) -> None:
    if not _table_exists(conn, "project_structure"):
        return
    rows = conn.execute(
        "SELECT id, payload FROM project_structure "
        "WHERE project_id=%s AND family='deploy_defaults'",
        (project_id,),
    ).fetchall()
    for row in rows:
        try:
            payload = json.loads(str(row[1]))
        except (TypeError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        if payload.get("deployment_flow") != predecessor_id:
            continue
        updated = dict(payload)
        updated["deployment_flow"] = successor_id
        if _column_exists(conn, "project_structure", "updated_at"):
            conn.execute(
                "UPDATE project_structure SET payload=%s, updated_at=%s "
                "WHERE id=%s",
                (json.dumps(updated, separators=(",", ":")), iso8601_now(), row[0]),
            )
        else:
            conn.execute(
                "UPDATE project_structure SET payload=%s WHERE id=%s",
                (json.dumps(updated, separators=(",", ":")), row[0]),
            )


def _converge_builtin_flow_supersessions(conn) -> None:
    """Activate exact code-owned successors without rewriting history.

    A predecessor is eligible only when every mutable definition field exactly
    matches a recognized code-owned shape and its successor exactly matches the
    current seed. Modified/project-authored definitions therefore remain
    untouched. Future assignments move to the successor through the project
    default; the predecessor is disabled only after all item and run bindings
    are terminal, so historical rows keep resolving their original stages.
    """

    seed_by_id = {str(flow["id"]): flow for flow in _SEED_FLOWS}
    for supersession in BUILTIN_FLOW_SUPERSESSIONS:
        predecessor_id = str(supersession["predecessor_id"])
        successor_id = str(supersession["successor_id"])
        successor = seed_by_id.get(successor_id)
        if successor is None:
            continue
        predecessor_row = _flow_definition_row(conn, predecessor_id)
        successor_row = _flow_definition_row(conn, successor_id)
        if predecessor_row is None or successor_row is None:
            continue
        project_id = int(tuple(predecessor_row)[0])
        if project_id != int(tuple(successor_row)[0]):
            continue
        if not _row_matches_definition(successor_row, successor):
            continue
        recognized = supersession.get("recognized_definitions") or ()
        if not any(
            _row_matches_definition(predecessor_row, definition)
            for definition in recognized
            if isinstance(definition, Mapping)
        ):
            continue
        _repoint_builtin_deploy_default(
            conn, project_id, predecessor_id, successor_id
        )
        if not _has_nonterminal_binding(conn, predecessor_id):
            conn.execute(
                "UPDATE deployment_flows SET status=%s WHERE id=%s",
                ("disabled", predecessor_id),
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
    _converge_builtin_flow_supersessions(conn)
    conn.commit()


def cmd_init(conn) -> str:
    _ensure_flow_schema(conn)
    _seed_missing_flow_definitions(conn)

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

    _converge_builtin_flow_supersessions(conn)
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
