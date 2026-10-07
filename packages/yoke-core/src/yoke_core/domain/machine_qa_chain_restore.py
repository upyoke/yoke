"""Credential-local reset and restore around one machine-run case chain.

The runner resets the Test Machine to a chain's declared baseline before the
chain's first case and restores that baseline after the chain's last case —
or after any case that did not pass, since its inheriting followers will not
run. A chain that started ``as_is`` has no declared state to go back to, and
says so in its evidence instead of pretending to restore.
"""

from __future__ import annotations

from typing import Any

from yoke_contracts.qa_case_starting_state import AS_IS, INHERIT

STARTING_STATE_RESTORE = "starting_state_restore"
STARTING_STATE_RESET_FAILED = "starting_state_reset_failed"
STARTING_STATE_RESTORE_FAILED = "starting_state_restore_failed"


def baseline_receipt(
    name: str, reach: Any, *, failure_code: str = STARTING_STATE_RESTORE_FAILED
) -> dict[str, Any]:
    """Evidence for one baseline the runner tried to reach."""
    try:
        reached = reach(name)
    except Exception as exc:  # the receipt carries the failure; callers decide
        return {
            "baseline": name,
            "ok": False,
            "error_code": failure_code,
            "diagnostic": f"{type(exc).__name__}: {exc}",
        }
    return {
        "baseline": name,
        "ok": bool(reached.ok),
        "error_code": reached.error_code,
        "evidence": reached.evidence,
    }


def restore_due(case: Any, case_outcome: str | None) -> bool:
    """Whether the machine goes back to the chain's start after this case."""
    return bool(case.ends_chain) or case_outcome != "passed"


def restore_chain_start(case: Any, reach: Any, *, machine: str) -> dict[str, Any]:
    """Restore the chain's starting state and return the evidence to record."""
    if case.starting_state == AS_IS or (
        case.starting_state == INHERIT and not case.host_baseline
    ):
        return {
            "restored": False,
            "reason": (
                "the chain started on the machine as found, so it has no "
                "declared starting state to restore"
            ),
        }
    receipt = baseline_receipt(str(case.host_baseline), reach)
    if not receipt["ok"]:
        receipt["recovery"] = (
            f"Test Machine {machine!r} was not returned to "
            f"{case.host_baseline!r}; run `yoke test-machine reset --project "
            f"{case.project} --machine {machine} --baseline "
            f"{case.host_baseline}` before the next machine QA run uses it"
        )
    return {"restored": bool(receipt["ok"]), **receipt}


def restore_summary(restore: dict[str, Any]) -> str:
    """One line naming what the restore did, for refusals and notes."""
    if restore.get("restored"):
        return f"starting state restored to {restore['baseline']!r}"
    if "baseline" not in restore:
        return str(restore["reason"])
    return (
        f"starting state restore to {restore['baseline']!r} failed "
        f"({restore.get('error_code') or 'unknown'}); {restore['recovery']}"
    )


__all__ = [
    "STARTING_STATE_RESET_FAILED",
    "STARTING_STATE_RESTORE",
    "STARTING_STATE_RESTORE_FAILED",
    "baseline_receipt",
    "restore_chain_start",
    "restore_due",
    "restore_summary",
]
