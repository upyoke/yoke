"""Handler for ``strategy.seed_defaults.run`` — default placeholder top-up.

DB-first per-slug top-up: seeds a placeholder row for each default slug
(:data:`yoke_core.domain.strategy_docs_defaults.DEFAULT_STRATEGY_DOC_SLUGS`)
the project is missing, parameterized by the project's display name.
Idempotent per slug — an existing row is never touched, so re-runs,
install-refresh paths, and projects predating a roster addition can call
it unconditionally: ``yoke strategy seed-defaults`` is the healer that
brings an established corpus up to the full default roster. Files are
rendered FROM the seeded rows afterwards (``strategy.render.run`` / the
install bundle); this handler never touches the filesystem.

No claim gate: seeding only ever inserts missing slugs, so there is no
existing content a racing writer could lose; the unique
``(project_id, slug)`` index serializes concurrent seeders.
"""

from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, ConfigDict, Field

from yoke_core.domain import events as _events
from yoke_core.domain.handlers.strategy_docs import _validate
from yoke_core.domain.handlers.strategy_docs_project import (
    resolve_request_project,
)
from yoke_core.domain.strategy_docs_defaults import seed_default_docs
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    HandlerOutcome,
)

STRATEGY_DEFAULTS_SEEDED_EVENT_NAME = "StrategyDefaultsSeeded"


class SeedDefaultsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SeedDefaultsResponse(BaseModel):
    project_id: int
    project_slug: str
    seeded: List[str] = Field(default_factory=list)
    already_present: List[str] = Field(default_factory=list)
    existing_rows: int = 0
    already_seeded: bool = False


def handle_seed_defaults(request: FunctionCallRequest) -> HandlerOutcome:
    _, err = _validate(request, SeedDefaultsRequest, "strategy.seed_defaults.run")
    if err is not None:
        return err
    from yoke_core.domain.db_helpers import connect

    with connect() as conn:
        project, perr = resolve_request_project(conn, request)
        if perr is not None:
            return perr
        report = seed_default_docs(conn, project.id, project.name)
    if report["seeded"]:
        _events.emit_event(
            STRATEGY_DEFAULTS_SEEDED_EVENT_NAME,
            event_kind="workflow",
            event_type="strategy_doc",
            source_type="agent",
            session_id=request.actor.session_id,
            severity="INFO",
            outcome="completed",
            project=project.slug,
            context={
                "project_id": project.id,
                "project_slug": project.slug,
                "seeded": report["seeded"],
                "already_present": report["already_present"],
            },
        )
    return HandlerOutcome(
        result_payload=SeedDefaultsResponse(
            project_id=project.id, project_slug=project.slug,
            seeded=report["seeded"],
            already_present=report["already_present"],
            existing_rows=report["existing_rows"],
            already_seeded=report["already_seeded"],
        ).model_dump(),
        primary_success=True,
    )


REGISTRATIONS: List[Dict[str, Any]] = [
    {
        "function_id": "strategy.seed_defaults.run",
        "handler": handle_seed_defaults,
        "request_model": SeedDefaultsRequest,
        "response_model": SeedDefaultsResponse,
        "stability": "stable",
        "owner_module": "yoke_core.domain.handlers.strategy_docs_seed",
        "target_kinds": ["global"],
        "side_effects": ["db_write", "event_emit"],
        "emitted_event_names": [STRATEGY_DEFAULTS_SEEDED_EVENT_NAME],
        "guardrails": ["missing_slugs_only"],
        "adapter_status": "live",
        "claim_required_kind": None,
        "ambient_session_required": False,
    },
]


__all__ = [
    "REGISTRATIONS",
    "STRATEGY_DEFAULTS_SEEDED_EVENT_NAME",
    "SeedDefaultsRequest",
    "SeedDefaultsResponse",
    "handle_seed_defaults",
]
