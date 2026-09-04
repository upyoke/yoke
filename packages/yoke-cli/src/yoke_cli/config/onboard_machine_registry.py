"""Put this machine in the control-plane machine registry as onboarding applies.

Apply reaches this step with the connection written and verified and the
machine relay installed, so the plane is answering by the time the call goes
out — which is what lets a freshly onboarded machine hold its ``machines`` row
without waiting for someone to run ``yoke status`` on it. A machine with no row
is refused by name at launch, so "set up but unregistered" is not a state
onboarding should leave behind.

Registration is idempotent, and a refusal is reported on the Apply summary with
its recovery rather than failing the apply: a machine that connected is set up,
whatever the registry decided about it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from yoke_cli.config import onboard_apply_progress
from yoke_cli.config.machine_registration import (
    REGISTER_RECOVERY_COMMAND,
    register_this_machine,
)

REGISTER_ACTION = "register-machine"
# The registry names this host from its own machine config, so the plan step
# names the host rather than a value that would differ per machine.
REGISTER_TARGET = "this machine"


def plan_steps() -> list[dict[str, str]]:
    return [{"action": REGISTER_ACTION, "target": REGISTER_TARGET}]


def apply(
    config_path: str | Path,
    *,
    progress: onboard_apply_progress.ProgressCallback | None,
    report: dict[str, Any],
) -> None:
    """Register this machine, recording the outcome on the onboarding report."""
    onboard_apply_progress.emit(progress, REGISTER_ACTION, REGISTER_TARGET, "running")
    outcome = register_this_machine(config_path)
    onboard_apply_progress.emit(
        progress,
        REGISTER_ACTION,
        REGISTER_TARGET,
        "done" if outcome.get("registered") else "failed",
    )
    report["machine_registry"] = outcome


def summary_lines(fragment: Any) -> tuple[str, ...]:
    """The Apply-summary lines a refusal owes the operator; empty when registered."""
    if not isinstance(fragment, Mapping) or fragment.get("registered"):
        return ()
    reason = str(fragment.get("reason") or "the registry refused this machine")
    return (
        f"This machine is not in the machine registry: {reason}",
        f"Register it with `{REGISTER_RECOVERY_COMMAND}` — "
        "launches refuse an unregistered machine by name.",
    )


__all__ = [
    "REGISTER_ACTION",
    "REGISTER_TARGET",
    "apply",
    "plan_steps",
    "summary_lines",
]
