"""Bridge between the agents-render writer and the path-context families.

Enumerates the rendered Yoke agent packet outputs and their seed
sources, then registers each rendered file as a
:data:`yoke_core.domain.path_context.FAMILY_RENDER_TARGET` with its
seed-source list. The overlap classifier consults the resulting rows
through :func:`read_render_source_for` to recognise false-positive
overlap on deterministic rendered output.

Scope (v0): Yoke agent packet outputs emitted by
:mod:`yoke_core.domain.agents_render` for the canonical ``AGENTS``
list. Non-packet generated surfaces (BOARD, event-catalog, function
inventory) are not in scope for this slice.

Public surface:

- :func:`render_relationship_map` — pure data: render-target path
  string → sorted list of seed-source path strings. Read by tests and
  the integrity invariant; no DB access.
- :func:`set_render_relationship` / :func:`read_render_source_for` —
  thin wrappers around ``path_context_values`` that operate on the
  render-relationship families. Skip silently when no path_targets row
  exists for the rendered file (opportunistic registration).
- :func:`record_render_relationships` — emit one batch-level
  ``RenderRelationshipRecorded`` event and write/refresh every
  relationship row idempotently.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from yoke_core.domain.event_registry_seed_render_relationship import (
    EVENT_NAME_RENDER_RELATIONSHIP_RECORDED,
)
from yoke_core.domain.events import emit_event
from yoke_core.domain.path_context import (
    FAMILY_RENDER_SOURCE,
    FAMILY_RENDER_TARGET,
    put_context_value,
    read_context_value,
)


# Shared seed-source modules every rendered packet inherits. The
# renderer's composition modules are the same for every output, so they
# are part of every rendered packet's seed-source set.
_CORE_DOMAIN_SOURCE_ROOT = "packages/yoke-core/src/yoke_core/domain"
_SHARED_RENDERER_SOURCES: Sequence[str] = (
    f"{_CORE_DOMAIN_SOURCE_ROOT}/agents_render.py",
    f"{_CORE_DOMAIN_SOURCE_ROOT}/agents_render_claude.py",
    f"{_CORE_DOMAIN_SOURCE_ROOT}/agents_render_codex.py",
    f"{_CORE_DOMAIN_SOURCE_ROOT}/agents_render_conditional.py",
    f"{_CORE_DOMAIN_SOURCE_ROOT}/agents_render_context.py",
    f"{_CORE_DOMAIN_SOURCE_ROOT}/agents_render_field_note.py",
    f"{_CORE_DOMAIN_SOURCE_ROOT}/agents_render_hooks.py",
    f"{_CORE_DOMAIN_SOURCE_ROOT}/agents_render_manifests.py",
    f"{_CORE_DOMAIN_SOURCE_ROOT}/agents_render_subagent_hooks.py",
    f"{_CORE_DOMAIN_SOURCE_ROOT}/agents_render_workspace.py",
)

# Bash-capable agents inherit the schema/api context modules — their
# packets carry the rendered DB-packet block expanded from these seeds.
_BASH_CAPABLE_AGENTS: Sequence[str] = (
    "architect",
    "engineer",
    "tester",
    "simulator",
    "boss",
)

_SCHEMA_API_CONTEXT_SOURCES: Sequence[str] = (
    f"{_CORE_DOMAIN_SOURCE_ROOT}/schema_api_context.py",
    f"{_CORE_DOMAIN_SOURCE_ROOT}/schema_api_context_commands.py",
    f"{_CORE_DOMAIN_SOURCE_ROOT}/schema_api_context_commands_claims.py",
    f"{_CORE_DOMAIN_SOURCE_ROOT}/schema_api_context_commands_core.py",
    f"{_CORE_DOMAIN_SOURCE_ROOT}/schema_api_context_commands_core_epic_task.py",
    f"{_CORE_DOMAIN_SOURCE_ROOT}/schema_api_context_commands_core_operational.py",
    f"{_CORE_DOMAIN_SOURCE_ROOT}/schema_api_context_commands_project.py",
    f"{_CORE_DOMAIN_SOURCE_ROOT}/schema_api_context_commands_qa.py",
    f"{_CORE_DOMAIN_SOURCE_ROOT}/schema_api_context_commands_watchers.py",
    f"{_CORE_DOMAIN_SOURCE_ROOT}/schema_api_context_json_schemas.py",
    f"{_CORE_DOMAIN_SOURCE_ROOT}/schema_api_context_render.py",
    f"{_CORE_DOMAIN_SOURCE_ROOT}/schema_api_context_seed.py",
    f"{_CORE_DOMAIN_SOURCE_ROOT}/schema_api_context_tables.py",
    f"{_CORE_DOMAIN_SOURCE_ROOT}/schema_api_context_tables_auth.py",
    f"{_CORE_DOMAIN_SOURCE_ROOT}/schema_api_context_tables_claims.py",
    f"{_CORE_DOMAIN_SOURCE_ROOT}/schema_api_context_tables_core.py",
    f"{_CORE_DOMAIN_SOURCE_ROOT}/schema_api_context_tables_project.py",
    f"{_CORE_DOMAIN_SOURCE_ROOT}/schema_api_context_tables_python_helpers.py",
    f"{_CORE_DOMAIN_SOURCE_ROOT}/schema_api_context_tables_qa.py",
)


def _sources_for_agent(agent: str) -> List[str]:
    """Return the sorted, deduped seed-source list for a single agent."""
    sources = {f"runtime/agents/{agent}.md"}
    sources.update(_SHARED_RENDERER_SOURCES)
    if agent in _BASH_CAPABLE_AGENTS:
        sources.update(_SCHEMA_API_CONTEXT_SOURCES)
    return sorted(sources)


def render_relationship_map() -> Dict[str, List[str]]:
    """Return ``{rendered_path: [seed_source_paths]}`` for every agent packet.

    Both the Claude ``.md`` and Codex ``.toml`` outputs of each agent
    map to the same seed-source set — the renderer reads the same
    canonical body and composition modules for both adapter formats.
    """
    # Imported lazily so importing this module does not pull in the full
    # renderer surface (and its workspace anchor side effects).
    from yoke_core.domain.agents_render import AGENTS

    relationships: Dict[str, List[str]] = {}
    for agent in AGENTS:
        sources = _sources_for_agent(agent)
        relationships[f"runtime/harness/claude/agents/yoke-{agent}.md"] = sources
        relationships[f"runtime/harness/codex/agents/yoke-{agent}.toml"] = sources
    return relationships


def set_render_relationship(
    conn: Any,
    *,
    target_path: str,
    source_paths: Sequence[str],
    recorded_event_id: str,
    project_id: str = "yoke",
) -> Optional[int]:
    """Record ``target_path`` as a render target with ``source_paths`` as seeds.

    Looks up the project-relative path_targets row for ``target_path``.
    When the row exists, writes/refreshes a single
    ``FAMILY_RENDER_TARGET`` ``path_context_values`` row with value
    ``{"sources": [...sorted seed path strings]}``. Each source that
    has its own path_targets row gets a parallel
    ``FAMILY_RENDER_SOURCE`` row keyed by the target path so the
    path-integrity invariant can detect missing target/source pairs.

    Returns the rendered target's row id on success; ``None`` when the
    target_path has no path_targets row yet (opportunistic registration).
    """
    from yoke_core.domain.path_registry import target_at

    target_id = target_at(conn, project_id, target_path)
    if target_id is None:
        return None
    normalised_sources = sorted({str(p) for p in source_paths if p})
    row_id = put_context_value(
        conn,
        target_id=target_id,
        context_family=FAMILY_RENDER_TARGET,
        entry_key="",
        value={"sources": normalised_sources},
        recorded_event_id=recorded_event_id,
    )
    for source_path in normalised_sources:
        source_target_id = target_at(conn, project_id, source_path)
        if source_target_id is None:
            continue
        put_context_value(
            conn,
            target_id=source_target_id,
            context_family=FAMILY_RENDER_SOURCE,
            entry_key=target_path,
            value={"target": target_path},
            recorded_event_id=recorded_event_id,
        )
    return row_id


def read_render_source_for(
    conn: Any, *, target_id: int,
) -> Optional[List[str]]:
    """Return the seed-source path strings registered for a render target.

    Reads the ``FAMILY_RENDER_TARGET`` row attached to ``target_id``.
    Returns ``None`` when no relationship is registered. The classifier
    consults this to decide whether overlap on the rendered file is
    provably independent at the seed-source layer.
    """
    value = read_context_value(
        conn,
        target_id=target_id,
        context_family=FAMILY_RENDER_TARGET,
        entry_key="",
    )
    if value is None:
        return None
    sources = value.get("sources") if isinstance(value, dict) else None
    if isinstance(sources, list):
        return [str(s) for s in sources if isinstance(s, str)]
    return None


def record_render_relationships(
    conn: Any,
    *,
    project_id: str = "yoke",
    session_id: str = "",
) -> int:
    """Emit one batch event and write every render relationship row.

    Returns the number of render targets that received a row (0 when no
    path_targets rows exist for any of the rendered files — the
    opportunistic case where the registry has not seen them yet). The
    emission is idempotent: existing rows are refreshed in place via
    the ``put_context_value`` upsert path.
    """
    relationships = render_relationship_map()
    result = emit_event(
        EVENT_NAME_RENDER_RELATIONSHIP_RECORDED,
        event_kind="lifecycle",
        event_type="path_context",
        source_type="backend",
        session_id=session_id,
        project=project_id,
        context={"render_target_count": len(relationships)},
        conn=conn,
    )
    if not result.event_id:
        return 0
    written = 0
    for target_path in sorted(relationships):
        sources = relationships[target_path]
        row_id = set_render_relationship(
            conn,
            target_path=target_path,
            source_paths=sources,
            recorded_event_id=result.event_id,
            project_id=project_id,
        )
        if row_id is not None:
            written += 1
    return written


def record_render_relationships_to_canonical_db(
    *,
    db_path: Optional[str] = None,
    project_id: str = "yoke",
    session_id: str = "",
) -> int:
    """Open a short-lived connection to the canonical DB and register.

    Resilient by design: a missing DB, missing schema, or empty
    path_targets registry returns ``0`` without raising. Callers in the
    renderer CLI / function-call handler treat the return value as
    advisory.
    """
    try:
        from yoke_core.domain.db_helpers import connect
    except Exception:
        return 0
    try:
        conn = connect(db_path) if db_path else connect()
    except Exception:
        return 0
    try:
        written = record_render_relationships(
            conn,
            project_id=project_id,
            session_id=session_id,
        )
        conn.commit()
        return written
    except Exception:
        return 0
    finally:
        conn.close()


__all__ = [
    "EVENT_NAME_RENDER_RELATIONSHIP_RECORDED",
    "FAMILY_RENDER_SOURCE",
    "FAMILY_RENDER_TARGET",
    "read_render_source_for",
    "record_render_relationships",
    "record_render_relationships_to_canonical_db",
    "render_relationship_map",
    "set_render_relationship",
]
