"""PostToolUse Agent-tool hook: auto-capture subagent reflections.

The canonical capture surface for reflection blocks. Wired into the
universal PostToolUse chain for the ``Agent`` matcher by
:mod:`yoke_contracts.hook_runner.hook_ordering`; the Claude harness's
adapter renders the matching ``settings.json`` block. When an Agent
tool call completes, this hook:

1. Reads ``payload["tool_response"]`` (full content, not the 4096-char
   preview ``observe_parsing._extract_response_text`` would return).
2. Maps ``payload["tool_input"]["subagent_type"]`` (``yoke-engineer``,
   ``yoke-tester``, ...) to the canonical role (``engineer``,
   ``tester``, ...).
3. Resolves the in-flight item's ``project`` field (best-effort), falls
   back to ``yoke``.
4. Calls
   :func:`yoke_core.domain.reflection_capture.capture_reflections`
   with the extracted text + role + project.
5. Emits ``ReflectionCaptureHookFired`` with the structured
   :class:`CaptureResult` counts.
6. When ``result.blocks_unrecognized > 0`` ALSO emits
   ``ReflectionCaptureHookUnhandled`` carrying the raw block excerpts so
   operators can grow the parser to cover the new shape.

Always returns ``AUDIT_ONLY`` — reflection capture is non-blocking by
contract. Any parse error or persistence failure is recorded in the
hook event payload and the corresponding ``ouroboros_entries`` rows are
skipped without aborting the tool call.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Optional

from runtime.harness.hook_runner.types import HookContext, HookDecision, Next, Outcome


TARGET_TOOL = "Agent"
DEFAULT_PROJECT = "yoke"
EVENT_FIRED = "ReflectionCaptureHookFired"
EVENT_UNHANDLED = "ReflectionCaptureHookUnhandled"

_ROLE_MAP: dict[str, str] = {
    "yoke-engineer": "engineer",
    "yoke-tester": "tester",
    "yoke-simulator": "simulator",
    "yoke-architect": "architect",
    "yoke-boss": "boss",
    "yoke-product-manager": "product_manager",
    "yoke-product-designer": "product_designer",
}


def _extract_full_response_text(response: Any) -> str:
    """Return the FULL response text (no 4096-char truncation)."""
    if isinstance(response, dict):
        response = response.get("content", "")
    if isinstance(response, list):
        parts: list[str] = []
        for c in response:
            if isinstance(c, dict):
                parts.append(str(c.get("text", "")))
            else:
                parts.append(str(c))
        return "".join(parts)
    if isinstance(response, str):
        return response
    return ""


def _resolve_role(subagent_type: Optional[str]) -> str:
    if not subagent_type or not isinstance(subagent_type, str):
        return "unknown"
    return _ROLE_MAP.get(subagent_type, subagent_type.removeprefix("yoke-"))


def _resolve_project(item_id: Optional[int]) -> str:
    if not item_id:
        return DEFAULT_PROJECT
    try:
        from yoke_core.domain import db_backend
        from yoke_core.domain.db_helpers import connect
        conn = connect()
        try:
            p = "%s" if db_backend.connection_is_postgres(conn) else "?"
            row = conn.execute(
                "SELECT p.slug FROM items i "
                "LEFT JOIN projects p ON p.id = i.project_id "
                f"WHERE i.id = {p}",
                (int(item_id),),
            ).fetchone()
        finally:
            conn.close()
        if row and row[0]:
            return row[0]
    except Exception:
        pass
    return DEFAULT_PROJECT


def _emit_event(event_name: str, payload: dict[str, Any], session_id: Optional[str]) -> None:
    """Best-effort event emission. Hook never blocks on emission failure.

    Emission failures log to stderr instead of silently swallowing the
    exception. A bare ``except Exception: pass`` can hide production
    reflection loss; a ``payload=`` kwarg typo
    raised ``TypeError`` on every fire from 2026-05-23 to 2026-05-25,
    silently dropping every reflection until the dispatch was rerouted).
    Stderr noise is preferable to silent data loss.
    """
    try:
        from yoke_core.domain.events import emit_event
        emit_event(
            event_name,
            event_kind="hook",
            event_type="reflection_capture",
            context=payload,
            session_id=session_id or "",
        )
    except Exception as exc:
        sys.stderr.write(
            f"reflection_capture_hook._emit_event failed: "
            f"{type(exc).__name__}: {exc}\n",
        )


def _capture_result_payload(result: Any) -> dict[str, Any]:
    """Project a :class:`CaptureResult` into the event payload shape."""
    return {
        "blocks_seen": getattr(result, "blocks_seen", 0),
        "blocks_parsed_successfully": getattr(result, "blocks_parsed_successfully", 0),
        "blocks_skipped_known_falsepositive": getattr(
            result, "blocks_skipped_known_falsepositive", 0,
        ),
        "blocks_unrecognized": getattr(result, "blocks_unrecognized", 0),
        "blocks_partial_no_end_marker": getattr(
            result, "blocks_partial_no_end_marker", 0,
        ),
        "entries_persisted": getattr(result, "entries_persisted", 0),
        "entries_duplicate_skipped": getattr(result, "entries_duplicate_skipped", 0),
        "entries_persist_failed": getattr(result, "entries_persist_failed", 0),
        "error_count": len(getattr(result, "errors", []) or []),
    }


def evaluate(record: HookContext) -> HookDecision:
    """Typed entry. Always returns ``AUDIT_ONLY``.

    Non-Agent tool names and any payload-shape miss short-circuit to an
    immediate no-op so the hook never blocks tool use.
    """
    payload = record.payload if isinstance(record.payload, dict) else {}
    tool = record.tool_name or payload.get("tool_name")
    if tool != TARGET_TOOL:
        return HookDecision(outcome=Outcome.AUDIT_ONLY, next=Next.CONTINUE)

    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return HookDecision(outcome=Outcome.AUDIT_ONLY, next=Next.CONTINUE)
    tool_response = payload.get("tool_response")

    response_text = _extract_full_response_text(tool_response)
    if "REFLECTION-START" not in response_text and "REFLECTION-END" not in response_text:
        return HookDecision(outcome=Outcome.AUDIT_ONLY, next=Next.CONTINUE)

    role = _resolve_role(tool_input.get("subagent_type"))
    project = _resolve_project(record.item_id)

    try:
        from yoke_core.domain.reflection_capture import capture_reflections
        result = capture_reflections(
            response_text, default_agent=role, project=project,
        )
    except Exception as exc:
        # Capture failures are non-blocking; record on the event.
        _emit_event(EVENT_FIRED, {
            "tool_use_id": tool_input.get("tool_use_id")
            or payload.get("tool_use_id"),
            "subagent_type": tool_input.get("subagent_type"),
            "role": role,
            "project": project,
            "error": f"capture_reflections raised: {type(exc).__name__}: {exc}",
        }, session_id=record.session_id)
        return HookDecision(outcome=Outcome.AUDIT_ONLY, next=Next.CONTINUE)

    fired_payload = _capture_result_payload(result)
    fired_payload.update({
        "tool_use_id": tool_input.get("tool_use_id")
        or payload.get("tool_use_id"),
        "subagent_type": tool_input.get("subagent_type"),
        "role": role,
        "project": project,
    })
    _emit_event(EVENT_FIRED, fired_payload, session_id=record.session_id)

    if getattr(result, "blocks_unrecognized", 0) > 0:
        examples = getattr(result, "unrecognized_block_examples", []) or []
        _emit_event(EVENT_UNHANDLED, {
            "tool_use_id": tool_input.get("tool_use_id")
            or payload.get("tool_use_id"),
            "subagent_type": tool_input.get("subagent_type"),
            "role": role,
            "project": project,
            "blocks_unrecognized": result.blocks_unrecognized,
            "raw_examples": examples,
        }, session_id=record.session_id)

    return HookDecision(outcome=Outcome.AUDIT_ONLY, next=Next.CONTINUE)


def main() -> None:
    """CLI entry — reads a JSON-encoded hook envelope on stdin.

    Permits the universal ``python3 -m runtime.harness.hook_runner
    PostToolUse`` runner to dispatch this module by name.
    """
    try:
        envelope = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    if not isinstance(envelope, dict):
        sys.exit(0)
    context = HookContext(
        event_name=envelope.get("hook_event_name", "PostToolUse"),
        executor_family=envelope.get("executor_family", "claude"),
        executor_surface=envelope.get("executor_surface", "claude-code"),
        payload=envelope,
        tool_name=envelope.get("tool_name"),
        command_body=None,
        cwd=envelope.get("cwd"),
        session_id=envelope.get("session_id") or os.environ.get("YOKE_SESSION_ID"),
        item_id=envelope.get("item_id"),
    )
    decision = evaluate(context)
    # The shared hook runner consumes the typed HookDecision; the CLI
    # path emits a tiny JSON line so direct invocations stay diagnosable.
    print(json.dumps({
        "outcome": decision.outcome.value,
        "block": decision.block,
    }))


if __name__ == "__main__":
    main()


__all__ = [
    "EVENT_FIRED",
    "EVENT_UNHANDLED",
    "TARGET_TOOL",
    "evaluate",
    "main",
]
