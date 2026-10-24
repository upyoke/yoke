"""The integration dependency gate, asked once before any landing route.

An item whose integration predecessors have not merged may not land, whether
it lands through the standalone engine or through a merge queue. Queue
admission only sees predecessors that are currently queue members, so a
predecessor still implementing would otherwise slip past it. The landing
router asks this gate before it selects a route, so both routes share it.
"""

from __future__ import annotations

from typing import Any, Callable

from yoke_contracts.refusal_recovery import compose_refusal

from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain.public_item_target import public_item_target

DEPENDENCY_GATE_FUNCTION_ID = "merge.preflight.dependency_gate"


def integration_dependency_refusal(
    *,
    item_id: int,
    public_ref: str,
    resume_command: str = "",
    dispatch: Callable[..., Any] = call_dispatcher,
) -> str:
    """Why this item may not land yet, or empty when its gate is clear.

    Fails closed on an unreadable answer: a landing that cannot ask whether
    its predecessors merged must not land.
    """
    ref = public_ref or str(item_id)
    rerun = resume_command or f"yoke merge item {ref}"
    try:
        response = dispatch(
            function_id=DEPENDENCY_GATE_FUNCTION_ID,
            target=public_item_target(public_ref or item_id),
            payload={"gate_point": "integration"},
        )
    except Exception as exc:  # noqa: BLE001 - reported as a named refusal.
        return _unavailable(ref, str(exc), rerun)
    if not getattr(response, "success", False):
        error = getattr(response, "error", None)
        detail = getattr(error, "message", None) or "dependency gate read failed"
        return _unavailable(ref, str(detail), rerun)
    result = getattr(response, "result", None) or {}
    if not result.get("is_blocked"):
        return ""
    lines = [
        f"integration_dependency_blocked: {ref} may not land until its "
        "integration dependencies merge:"
    ]
    for blocker in result.get("unsatisfied_blockers") or []:
        lines.append(
            f"  - {blocker.get('blocking_item', '?')} "
            f"({blocker.get('blocking_status') or 'unknown status'}): "
            f"{blocker.get('rationale') or 'no rationale'}"
        )
    lines.append(
        compose_refusal(
            (
                "Keep your work claim and lane; do not release or end the session; the "
                "notice wakes you as holder. Park with `yoke sessions touch --mode parked "
                '--reason "awaiting <BLOCKER> integration"`.'
            ),
            recovery=f"wait for each blocker to merge (the control plane sends a notice when it does), then re-run `{rerun}`. If the dependency is wrong, correct it first with `yoke items dependency update` or `yoke items dependency remove`.",
        )
    )
    return "\n".join(lines)


def _unavailable(ref: str, detail: str, rerun: str) -> str:
    return compose_refusal(
        f"integration_dependency_gate_unavailable: could not evaluate the integration dependency gate for {ref}: {detail}.",
        recovery=f"restore control-plane access, then re-run `{rerun}`.",
    )
