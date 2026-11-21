"""Render a plan case waiting for its Test Machine turn."""

from typing import Any, Mapping


def waiting_case(
    begun: Mapping[str, Any], requirement_id: int, *, runner_id: str
) -> dict[str, Any]:
    """A queued case: its place in the Test Machine queue and the park
    instruction. A server without the queue fields renders no place."""
    wait = begun.get("host_wait") or {}
    hosts = (
        f"QA hosts {wait['waits_for']}"
        if len(wait.get("test_machines") or ()) > 1
        else f"QA host {wait.get('test_machine') or 'its Test Machine'}"
    )
    position = wait.get("position_text")
    place = f", {position}" if position else ""
    because = f" ({wait['rationale']})" if wait.get("rationale") else ""
    return {
        "requirement_id": requirement_id,
        "runner_id": runner_id,
        "verdict": "waiting",
        "case_outcome": "waiting",
        "lease_context": begun.get("lease_context"),
        "host_wait": begun.get("host_wait"),
        "recovery": (
            f"Queued for {hosts}{place}{because}. Park now: "
            f'`yoke sessions touch --mode parked --reason "queued for {hosts}"`. '
            "When it is your turn, a host-turn message wakes this session with "
            "the command that takes it. Write no hold of your own; re-running "
            "this plan keeps your place."
        ),
    }
