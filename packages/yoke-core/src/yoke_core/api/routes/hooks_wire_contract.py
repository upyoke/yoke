"""The frozen request and response shapes of one hook evaluation.

Split from the route so the contract a client encodes against is readable
on its own. Both sides carry ``hook_schema``: a client and a server that
disagree about it must not half-interpret each other, so the route
refuses an unknown value outright rather than reading the fields it
happens to recognize.

Client-resolved fields dominate this shape because the server cannot
observe them. Only the machine running the harness can read that
harness's own artifacts — what a provider served, what it charged — and
only the client's own environment states what was asked for.
"""

from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field

from yoke_contracts.hook_evaluator_protocol import HOOK_EVALUATOR_CAPABILITIES


#: Version tag for the hook-evaluate wire contract (request and response).
HOOK_WIRE_SCHEMA = 1


class HookEvaluateRequest(BaseModel):
    """Frozen request contract for one hook evaluation."""

    hook_schema: int = HOOK_WIRE_SCHEMA
    event_name: str
    stdin: str = ""
    executor: str = "claude"
    agent_type: Optional[str] = None
    entrypoint: Optional[str] = None
    #: Provider-attested served facts, resolved on the client because only
    #: that machine can read the harness artifact.
    model: Optional[str] = None
    reasoning_effort: Optional[str] = None
    context_window_tokens: Optional[int] = None
    #: The session's stated ask, resolved from the client's launch env.
    requested_model: Optional[str] = None
    requested_reasoning_effort: Optional[str] = None
    requested_context_window_tokens: Optional[int] = None
    #: This session's consumption as the relaying client's own machine
    #: read it, serialized by ``session_usage_facts.usage_document``.
    usage_totals: Optional[str] = None
    execution_lane: Optional[str] = None
    project_id: Optional[int] = None
    executor_version: Optional[str] = None
    machine_id: Optional[str] = None
    native_thread_id: Optional[str] = None
    payload_extra: dict[str, Any] = Field(default_factory=dict)
    deadline_ms: Optional[int] = None
    execution_provenance: dict[str, Any] = Field(default_factory=dict)


class HookEvaluateResponse(BaseModel):
    """Relayed stdout/exit code and the structured composition outcome."""

    hook_schema: int = HOOK_WIRE_SCHEMA
    stdout: str
    exit_code: int
    wait_ms: int
    degraded: List[str]
    outcome: str
    model_confirmation: Optional[str] = None
    capabilities: tuple[str, ...] = HOOK_EVALUATOR_CAPABILITIES


__all__ = ["HOOK_WIRE_SCHEMA", "HookEvaluateRequest", "HookEvaluateResponse"]
