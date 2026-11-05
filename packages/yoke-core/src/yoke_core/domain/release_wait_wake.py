"""Wake facts and instructions for a session waiting on delivery."""

from collections.abc import Mapping
from typing import Any
from yoke_contracts.session_control.capabilities import operator_wake_instruction
from yoke_core.domain.session_message_routing import messageability

#: Yoke resumes this surface natively when a stage needs it.
WAKE_NATIVE = "native"
#: Only the person whose window it is may resume it.
WAKE_OPERATOR = "operator"
#: The surface declares no stopped-session wake route at all.
WAKE_NONE = "none"
#: No session row was read, so wakeability is not established.
WAKE_UNREAD = "unread"


def session_wake(session: Any) -> dict[str, Any]:
    """Whether a stopped session on this registered surface can be woken."""
    if not isinstance(session, Mapping) or not session.get("executor_surface"):
        return {"kind": WAKE_UNREAD, "surface": ""}
    surface = str(session["executor_surface"])
    routing = messageability(dict(session), liveness="ended", force_stopped_route=True)
    if str(routing.get("wake_interface") or "none") != "none":
        kind = WAKE_NATIVE
    elif routing.get("wake_authority") == WAKE_OPERATOR:
        kind = WAKE_OPERATOR
    else:
        kind = WAKE_NONE
    return {
        "kind": kind,
        "surface": surface,
        "display_name": session.get("display_label"),
    }


def wake_line(wake: Mapping[str, Any], parked: str) -> str:
    kind = wake.get("kind")
    surface = wake.get("surface") or "this"
    if kind == WAKE_NATIVE:
        return f"wake: this {surface} session is woken natively when a stage needs it"
    if kind == WAKE_OPERATOR:
        return (
            f"wake: none will arrive — {operator_wake_instruction(surface, wake.get('display_name'))} "
            "A steering seat may ask the operator to re-enter it"
        )
    if kind == WAKE_NONE:
        return (
            f"wake: none will arrive — the {surface} surface declares no "
            "stopped-session wake route, so the operator or a steering seat "
            "must re-enter this session"
        )
    why = parked if parked and parked != "yes" else "the session read named no surface"
    return f"wake: not established ({why})"
