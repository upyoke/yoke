"""Pure inventory of generated tracked files and safe seed sources.

The path-context writer consumes this module after a project snapshot has
materialized committed paths. Static renderers contribute deterministic
targets, while the install-bundle mirror is derived from the live tracked
inventory instead of being hand-enumerated. A generator that preserves an
authored region is self-seeded so it cannot activate the output-only escape.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Dict, Iterable, List, Sequence

from yoke_contracts.project_contract.install_manifest import (
    PACKAGED_INSTALL_BUNDLE_TREE_REL,
)
from yoke_core.domain.agents_render_conditional import (
    HARNESS_IDS,
    RENDERED_AGENT_DIRS,
    rendered_agent_path,
)
from yoke_core.domain.populate_registry_render import EVENT_CATALOG_RELPATH
from yoke_core.tools.atlas_render_docs import ATLAS_RELPATH


_CORE_DOMAIN_SOURCE_ROOT = "packages/yoke-core/src/yoke_core/domain"
_CORE_TOOLS_SOURCE_ROOT = "packages/yoke-core/src/yoke_core/tools"

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

_ATLAS_RENDERER_SOURCES: Sequence[str] = (
    f"{_CORE_TOOLS_SOURCE_ROOT}/atlas_integrity_audit.py",
    f"{_CORE_TOOLS_SOURCE_ROOT}/atlas_integrity_collect.py",
    f"{_CORE_TOOLS_SOURCE_ROOT}/atlas_render_docs.py",
    f"{_CORE_TOOLS_SOURCE_ROOT}/atlas_render_docs_sections.py",
    f"{_CORE_TOOLS_SOURCE_ROOT}/atlas_render_docs_tables.py",
)

_EVENT_CATALOG_STATIC_SOURCES: Sequence[str] = (
    f"{_CORE_DOMAIN_SOURCE_ROOT}/populate_registry.py",
    f"{_CORE_DOMAIN_SOURCE_ROOT}/populate_registry_render.py",
)

_INSTALL_BUNDLE_PREFIX = f"{PACKAGED_INSTALL_BUNDLE_TREE_REL}/"
_RENDERED_AGENT_PREFIXES = tuple(
    f"{directory.as_posix()}/" for directory in RENDERED_AGENT_DIRS
)


def _sources_for_agent(agent: str) -> List[str]:
    sources = {f"runtime/agents/{agent}.md", *_SHARED_RENDERER_SOURCES}
    if agent in _BASH_CAPABLE_AGENTS:
        sources.update(_SCHEMA_API_CONTEXT_SOURCES)
    return sorted(sources)


def _agent_relationships() -> Dict[str, List[str]]:
    from yoke_core.domain.agents_render import AGENTS

    relationships: Dict[str, List[str]] = {}
    for harness_id in sorted(HARNESS_IDS):
        for agent in AGENTS:
            relationships[rendered_agent_path(harness_id, agent).as_posix()] = (
                _sources_for_agent(agent)
            )
    return relationships


def _is_atlas_input(path: str) -> bool:
    if path.startswith(".agents/skills/yoke/"):
        return True
    if path.startswith("runtime/agents/"):
        return True
    if path.startswith(_RENDERED_AGENT_PREFIXES):
        return True
    if path.startswith("runtime/api/domain/lint_") and path.endswith(".py"):
        return True
    if path.startswith(f"{_CORE_DOMAIN_SOURCE_ROOT}/schema_api_context"):
        return path.endswith(".py")
    if path.startswith("packages/yoke-cli/src/yoke_cli/commands/"):
        return path.endswith(".py")
    name = PurePosixPath(path).name
    return path.startswith("packages/yoke-cli/src/yoke_cli/") and name.startswith(
        ("operation_inventory", "product_boundary")
    )


def _atlas_sources(tracked_paths: set[str]) -> List[str]:
    sources = set(_ATLAS_RENDERER_SOURCES)
    sources.update(path for path in tracked_paths if _is_atlas_input(path))
    sources.discard(ATLAS_RELPATH)
    return sorted(sources)


def _event_catalog_sources(tracked_paths: set[str]) -> List[str]:
    sources = set(_EVENT_CATALOG_STATIC_SOURCES)
    for path in tracked_paths:
        if not path.startswith(f"{_CORE_DOMAIN_SOURCE_ROOT}/"):
            continue
        name = PurePosixPath(path).name
        if name.startswith(("event_registry_seed", "populate_registry")):
            sources.add(path)
    # The catalog renderer preserves the appendix below its sentinel. Naming
    # the target as a seed keeps authored appendix collisions incompatible.
    sources.add(EVENT_CATALOG_RELPATH)
    return sorted(sources)


def _install_bundle_relationships(
    tracked_paths: set[str],
) -> Dict[str, List[str]]:
    relationships: Dict[str, List[str]] = {}
    for target_path in sorted(tracked_paths):
        if not target_path.startswith(_INSTALL_BUNDLE_PREFIX):
            continue
        source_path = target_path[len(_INSTALL_BUNDLE_PREFIX) :]
        # The sync preserves a small allowed-extra set (currently the package
        # marker) rather than copying it. Self-seeding any target without a
        # tracked source prevents the generated-output escape on authored data.
        source = source_path if source_path in tracked_paths else target_path
        relationships[target_path] = [source]
    return relationships


def _normalise_path(path: object) -> str:
    normalised = str(path).replace("\\", "/")
    return normalised[2:] if normalised.startswith("./") else normalised


def render_relationship_map(
    tracked_paths: Iterable[str] = (),
) -> Dict[str, List[str]]:
    """Return every known render target mapped to sorted seed-source paths."""
    tracked = {_normalise_path(path) for path in tracked_paths if str(path).strip()}
    relationships = _agent_relationships()
    relationships[ATLAS_RELPATH] = _atlas_sources(tracked)
    relationships[EVENT_CATALOG_RELPATH] = _event_catalog_sources(tracked)
    relationships.update(_install_bundle_relationships(tracked))
    return dict(sorted(relationships.items()))


__all__ = ["render_relationship_map"]
