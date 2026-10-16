"""Registered server owner of the complete reflection capture pipeline."""

from __future__ import annotations

from dataclasses import asdict

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class CaptureRequest(BaseModel):
    text: str = Field(max_length=2_000_000)
    default_agent: str = "unknown"


class CaptureResponse(BaseModel):
    blocks_seen: int = 0
    blocks_parsed_successfully: int = 0
    blocks_skipped_known_falsepositive: int = 0
    blocks_unrecognized: int = 0
    blocks_partial_no_end_marker: int = 0
    entries_persisted: int = 0
    entries_duplicate_skipped: int = 0
    entries_persist_failed: int = 0
    unrecognized_block_examples: list[dict] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    entries_parsed: int = 0
    entries_skipped: int = 0


def handle_capture(request: FunctionCallRequest) -> HandlerOutcome:
    body = CaptureRequest.model_validate(request.payload)
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.project_identity import (
        resolve_project_id,
        resolve_project_slug,
    )
    from yoke_core.domain.reflection_capture import capture_reflections

    try:
        with connect() as conn:
            project_id = resolve_project_id(conn, str(request.target.project_id))
            result = capture_reflections(
                body.text,
                default_agent=body.default_agent,
                project=resolve_project_slug(conn, project_id),
                session_id=request.actor.session_id,
                _conn=conn,
            )
    except Exception as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="reflection_capture_failed",
                message=f"Capture could not complete: {type(exc).__name__}: {exc}",
                recovery_hint="Retain the response text, restore control-plane access, "
                "and rerun yoke ouroboros reflection capture with the same file and project.",
            ),
        )
    payload = asdict(result)
    incomplete = bool(
        result.errors
        or result.entries_persist_failed
        or result.blocks_unrecognized
        or result.blocks_partial_no_end_marker
    )
    return HandlerOutcome(
        primary_success=not incomplete,
        result_payload=payload,
        error=FunctionError(
            code="reflection_capture_incomplete",
            message="Some reflection content was not captured; inspect the returned counts and errors.",
            recovery_hint="Retain the response text, repair the named parse or persistence failure, "
            "then rerun yoke ouroboros reflection capture; existing entries are deduplicated.",
        )
        if incomplete
        else None,
    )


def register(registry) -> None:
    registry.register(
        "ouroboros.reflection.capture",
        handle_capture,
        CaptureRequest,
        CaptureResponse,
        stability="stable",
        owner_module=__name__,
        target_kinds=["global"],
        side_effects=["db_write"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
        minimum_serving_version="next-release",
    )
