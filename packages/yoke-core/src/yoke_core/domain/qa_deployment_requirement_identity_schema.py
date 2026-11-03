"""Open deployment case keys; ordered migration owns existing-data cutover."""

SHARED_GROUP_KEY = (
    "COALESCE(execution_target_json::jsonb #>> '{deployment,shared_plan,group_id}', '')"
)


def shared_group_id(target):
    return str(
        (((target or {}).get("deployment") or {}).get("shared_plan") or {}).get(
            "group_id"
        )
        or ""
    )


OBSOLETE_REQUIREMENT_INDEXES = (
    "idx_qa_requirement_deployment_stage_materialization",
    "idx_qa_requirement_deployment_member_stage_materialization",
)


def requirement_index_specs(execution_specs):
    names = (
        "idx_qa_requirement_deployment_legacy_materialization",
        "idx_qa_requirement_deployment_stage_open_case",
        "idx_qa_requirement_deployment_member_stage_open_case",
    )
    return tuple(
        (
            name,
            execution[1][: position + 1]
            + ("plan_id", "plan_case_key", "COALESCE(host_baseline, '')")
            + ((SHARED_GROUP_KEY,) if position == 1 else ()),
            execution[2]
            + " AND plan_id IS NOT NULL"
            + (
                " AND superseded_by_requirement_id IS NULL AND retracted_at IS NULL"
                if position
                else ""
            ),
        )
        for position, (name, execution) in enumerate(zip(names, execution_specs))
    )


def ensure_requirement_scope_indexes(conn):
    from yoke_core.domain.qa_deployment_scope_schema import (
        _REQUIREMENT_INDEX_SPECS,
        _index_sql,
    )
    from yoke_core.domain.schema_init_apply import execute_schema_script

    specs = _REQUIREMENT_INDEX_SPECS
    if any(
        conn.execute("SELECT to_regclass(%s)", (name,)).fetchone()[0] is not None
        for name in OBSOLETE_REQUIREMENT_INDEXES
    ):
        # Additive boot runs before history: duplicates must first converge
        # through the restore-point and serving-floor guarded migration.
        specs = specs[:1]
    execute_schema_script(conn, _index_sql("qa_requirements", specs))
