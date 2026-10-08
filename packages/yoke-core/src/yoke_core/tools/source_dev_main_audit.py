"""Record the narrow mapped-main source operation before it executes."""

from pathlib import Path
from typing import Sequence

MAIN_CHECKOUT_FALLBACK_EVENT = "SourceDevRunMainCheckoutFallback"


def record_main_checkout_fallback(
    *,
    session_id: str,
    root: Path,
    project_id: int,
    command: Sequence[str],
    authority_signature: str,
) -> str | None:
    """Record the audit boundary before a registered source command reads main."""
    try:
        from yoke_cli.transport.dispatcher import build_actor, call_dispatcher
        from yoke_contracts.api.function_call import TargetRef

        response = call_dispatcher(
            function_id="events.emit",
            target=TargetRef(kind="global"),
            payload={
                "name": MAIN_CHECKOUT_FALLBACK_EVENT,
                "kind": "audit",
                "type": "source_dev_run",
                "source_type": "script",
                "severity": "WARN",
                "outcome": "completed",
                "project": str(project_id),
                "context": {
                    "checkout": str(root),
                    "command_name": str(command[0]),
                    "argument_count": max(0, len(command) - 1),
                    "fallback_reason": "no_live_claimed_yoke_source_lane",
                    "authority_signature": authority_signature,
                },
            },
            actor=build_actor(session_id=session_id),
        )
    except Exception as exc:
        return f"could not record main-checkout fallback: {exc}"
    if not response.success:
        detail = response.error.message if response.error else "unknown error"
        return f"could not record main-checkout fallback: {detail}"
    result = response.result or {}
    if not result.get("emitted"):
        return (
            "could not record main-checkout fallback: "
            f"{result.get('reason') or 'event was not emitted'}"
        )
    return None
