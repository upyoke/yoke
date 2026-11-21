"""Read done-transition preconditions through the connected transport."""

from __future__ import annotations

import sys
from typing import Optional, Tuple

from yoke_core.domain.public_item_target import public_item_target


def check_done_preconditions(
    item_id: int,
    deploy_flow: str,
    require_plan_verdict: bool,
) -> Tuple[bool, Optional[str]]:
    """Run all four preconditions through the connected transport.

    Relays ``done_transition.done_preconditions`` so the precondition bundle
    runs over an https control plane as well as a local Postgres connection,
    then returns its ``(allowed, reason)`` verdict verbatim. A read failure
    raises, aborting the transition exactly as the inline ``connect()`` did
    on a DB-level failure — this gate never degrades to "allowed".
    """
    from yoke_core.api.service_client_structured_api_adapter import (
        call_dispatcher,
    )

    resp = call_dispatcher(
        function_id="done_transition.done_preconditions",
        target=public_item_target(item_id),
        payload={
            "deploy_flow": deploy_flow,
            "require_plan_verdict": require_plan_verdict,
        },
    )
    if not resp.success:
        message = resp.error.message if resp.error else "unknown error"
        raise RuntimeError(f"done preconditions read failed: {message}")
    data = resp.result or {}
    return bool(data.get("allowed")), data.get("reason")


def enforce_preconditions(
    item_id: int,
    deploy_flow: str,
    require_plan_verdict: bool,
) -> Optional[str]:
    """Runner hook: emit the guard banner on failure, return reason or None."""
    allowed, reason = check_done_preconditions(
        item_id,
        deploy_flow,
        require_plan_verdict,
    )
    if allowed:
        return None
    print("\n=== Done preconditions guard ===", file=sys.stderr)
    print(f"Blocked: {reason}", file=sys.stderr)
    return reason
