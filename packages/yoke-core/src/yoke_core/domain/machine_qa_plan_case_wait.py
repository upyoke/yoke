"""Render a plan case waiting for its Test Machine turn."""

from typing import Any, Mapping


def waiting_case(
    begun: Mapping[str, Any], requirement_id: int, *, runner_id: str
) -> dict[str, Any]:
    """A queued case: its place in the host's line and the park instruction."""
    wait = begun.get("host_wait") or {}
    test_machine = wait.get("test_machine") or "its Test Machine"
    place = (
        f", position {wait['position']} of {wait['line_length']}"
        if wait.get("position")
        else ""
    )
    because = f" ({wait['rationale']})" if wait.get("rationale") else ""
    return {
        "requirement_id": requirement_id,
        "runner_id": runner_id,
        "verdict": "waiting",
        "case_outcome": "waiting",
        "lease_context": begun.get("lease_context"),
        "host_wait": begun.get("host_wait"),
        "recovery": (
            f"Queued for QA host {test_machine}{place}{because}. Park now: "
            f'`yoke sessions touch --mode parked --reason "queued for QA host '
            f'{test_machine}"`. When it is your turn, a host-turn message wakes this '
            "session with the command that takes it. Write no hold of your own; "
            "re-running this plan keeps your place."
        ),
    }
