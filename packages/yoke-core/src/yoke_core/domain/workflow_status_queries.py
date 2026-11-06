"""Pinned-workflow predicates for item scans."""

from __future__ import annotations
from yoke_core.domain import db_backend
from yoke_core.domain.frontier_workflow_versions import load_frontier_workflow_versions
from yoke_contracts.lifecycle_status import ENGINE_TERMINAL_STAGE_IDS


def exclude_terminal_items(conn, *, alias: str = "i"):
    """Return an AND clause and parameters for nonterminal items."""
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    return load_frontier_workflow_versions(conn).skip_clause(
        marker,
        alias=alias,
        statuses=lambda runtime: runtime.all_terminal_stage_ids,
    )


def _membership_clause(conn, statuses, *, alias, status=None):
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    fragments, params = [], []
    for version_id, runtime in load_frontier_workflow_versions(conn).runtimes.items():
        stages = sorted(statuses(runtime))
        if not stages:
            continue
        fragments.append(
            f"({alias}.workflow_version_id={marker} AND {status or alias + '.status'} IN "
            f"({','.join(marker for _ in stages)}))"
        )
        params.extend((version_id, *stages))
    return "(" + " OR ".join(fragments or ["FALSE"]) + ")", params


def completed_items_sql(conn, *, alias="i", status=None):
    """Correlate successful membership without an extra database round trip."""
    status = status or f"{alias}.status"
    if db_backend.connection_is_postgres(conn):
        membership = f"(wv.definition_json::jsonb->'terminal_stage_ids') ? {status}"
        source = "workflow_versions wv"
    else:
        source = "workflow_versions wv, json_each(wv.definition_json, '$.terminal_stage_ids') terminal"
        membership = f"terminal.value={status}"
    return (
        f"EXISTS (SELECT 1 FROM {source} WHERE "
        f"wv.id={alias}.workflow_version_id AND {membership})"
    )


def terminal_items_sql(conn, *, alias="i"):
    """Correlate definition terminals and the shared engine cancellation set."""
    engine = ",".join("'" + stage + "'" for stage in sorted(ENGINE_TERMINAL_STAGE_IDS))
    return f"({alias}.status IN ({engine}) OR {completed_items_sql(conn, alias=alias)})"


def release_items_clause(conn, *, alias="i"):
    """SQL predicate for each pin's nonterminal delivery-ready stages."""
    return _membership_clause(
        conn,
        lambda runtime: frozenset(
            stage
            for stage in runtime.stage_ids
            if stage not in runtime.all_terminal_stage_ids
            and runtime.stage_implies_merge(stage)
        ),
        alias=alias,
    )


def landed_stages_clause(conn, *, alias="i", status=None):
    """SQL membership for stages whose pinned policy implies a landing."""
    return _membership_clause(
        conn,
        lambda runtime: frozenset(
            stage for stage in runtime.stage_ids if runtime.stage_implies_merge(stage)
        ),
        alias=alias,
        status=status,
    )
