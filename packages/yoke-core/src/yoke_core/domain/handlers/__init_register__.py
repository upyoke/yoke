"""Single entrypoint that wires every Yoke function handler into the registry.

Domain registrars live in sibling ``_register_<domain>.py`` modules. Add a new
domain by adding a new ``_register_<domain>.py`` and listing it in
``_DOMAIN_REGISTRARS`` below. This explicit list is the source of truth —
discovery order is deterministic and merge conflicts on this file are an
explicit signal that two domains are racing the same shared edit point. The
domain-keyed convention replaced the prior ``_register_task<N>.py`` ordinal
naming so file-path coordination is keyed to the handler concern rather than
an arbitrary next-integer slot; see
``docs/archive/decisions/handler-registrar-naming-convention.md``.

Idempotency contract: :func:`register_all_handlers` is callable safely
multiple times within one process. The function short-circuits once the
registry is populated, so the FastAPI ``lifespan`` running on every
``TestClient`` instantiation does not raise. Within a single registration
cycle, :func:`yoke_core.domain.yoke_function_registry.register`
still raises :class:`RegistryDuplicateError` on real id collisions —
the guard short-circuits only the already-fully-registered case.
"""
from __future__ import annotations

from yoke_core.domain import yoke_function_registry

from yoke_core.domain.handlers import (
    _register_claims,
    _register_db_read,
    _register_deployment,
    _register_ephemeral_env,
    _register_epic_tasks,
    _register_events_reads,
    _register_github,
    _register_github_actions,
    _register_hooks,
    _register_identity,
    _register_install,
    _register_items_create,
    _register_items_github_sync,
    _register_items_scalar_lifecycle,
    _register_items_structured,
    _register_machine_config,
    _register_onboard_checklist,
    _register_organizations,
    _register_ouroboros_field_notes,
    _register_ouroboros_reads,
    _register_project_structure_reads,
    _register_project_snapshot,
    _register_projects,
    _register_qa_crud,
    _register_qa_reads,
    _register_readiness,
    _register_scratch,
    _register_shepherd_reads,
    _register_sessions,
    _register_strategy,
    _register_templates,
)

_DOMAIN_REGISTRARS = (
    _register_items_create,
    _register_items_structured,
    _register_items_github_sync,
    _register_epic_tasks,
    _register_items_scalar_lifecycle,
    _register_machine_config,
    _register_onboard_checklist,
    _register_install,
    _register_templates,
    _register_db_read,
    _register_claims,
    _register_deployment,
    _register_ephemeral_env,
    _register_readiness,
    _register_qa_reads,
    _register_project_structure_reads,
    _register_project_snapshot,
    _register_projects,
    _register_organizations,
    _register_identity,
    _register_qa_crud,
    _register_events_reads,
    _register_ouroboros_field_notes,
    _register_ouroboros_reads,
    _register_shepherd_reads,
    _register_sessions,
    _register_hooks,
    _register_github_actions,
    _register_github,
    _register_scratch,
    _register_strategy,
)


def register_all_handlers() -> None:
    """Register every Yoke function handler, idempotently.

    Returns immediately when the registry already holds any entries — the
    FastAPI lifespan runs `register_all_handlers()` on every `TestClient`
    instantiation, so this guard makes the function safe to call repeatedly
    within the same process. Real handler-id collisions still raise
    `RegistryDuplicateError` from `yoke_core.domain.yoke_function_registry.register`
    because they are caught by the per-id check there; the guard here only
    short-circuits the already-fully-registered case.

    Tests that need a fresh registration cycle (e.g. function-dispatcher
    tests with a fake DB) opt in by calling
    `yoke_core.domain.yoke_function_registry.reset_registry_for_tests()`
    immediately before `register_all_handlers()`.
    """
    if yoke_function_registry.list_entries():
        return
    for module in _DOMAIN_REGISTRARS:
        module.register(yoke_function_registry)


__all__ = ["register_all_handlers"]
