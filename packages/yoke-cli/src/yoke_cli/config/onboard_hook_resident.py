"""Start the hook evaluator as ``yoke setup`` applies.

The first harness session on a machine must not pay the evaluator's cold
start inside its hook timeout, so every setup restarts the resident and
proves it answers a dry evaluation before any session opens. A failure is
reported on the Apply summary with its recovery rather than failing the
apply: the rest of the machine is set up either way.
"""

from __future__ import annotations

from typing import Any, Mapping

from yoke_cli import hook_resident_client
from yoke_cli.hook_resident_lifecycle import ResidentLifecycleError, restart_resident
from yoke_cli.config import onboard_apply_progress

RESTART_ACTION = "restart-hook-evaluator"
RESTART_TARGET = "yoke hook resident restart"
RECOVERY = (
    "Run yoke hook resident restart, then yoke watch doctor -- --only "
    "hook-resident, before opening a harness session."
)


def plan_steps() -> list[dict[str, str]]:
    if not hook_resident_client.resident_transport_available():
        return []
    return [{"action": RESTART_ACTION, "target": RESTART_TARGET}]


def apply(
    *,
    progress: onboard_apply_progress.ProgressCallback | None,
    report: dict[str, Any],
) -> None:
    """Restart the evaluator, recording the outcome on the onboarding report."""
    if not hook_resident_client.resident_transport_available():
        # Hooks evaluate in-process on this platform; there is nothing to warm.
        return
    onboard_apply_progress.emit(progress, RESTART_ACTION, RESTART_TARGET, "running")
    try:
        restart_resident()
    except (
        ResidentLifecycleError,
        hook_resident_client.ResidentUnavailable,
        OSError,
    ) as exc:
        report["hook_evaluator"] = {
            "ready": False,
            "reason": str(exc),
            "recovery": RECOVERY,
        }
        onboard_apply_progress.emit(progress, RESTART_ACTION, RESTART_TARGET, "failed")
        return
    report["hook_evaluator"] = {"ready": True}
    onboard_apply_progress.emit(progress, RESTART_ACTION, RESTART_TARGET, "done")


def summary_lines(fragment: Any) -> tuple[str, ...]:
    """The Apply-summary lines a failed start owes the operator; empty otherwise."""
    if not isinstance(fragment, Mapping) or not fragment.get("recovery"):
        return ()
    return (
        f"The hook evaluator did not start: {fragment.get('reason')}",
        str(fragment.get("recovery")),
    )


__all__ = ["RESTART_ACTION", "RESTART_TARGET", "apply", "plan_steps", "summary_lines"]
