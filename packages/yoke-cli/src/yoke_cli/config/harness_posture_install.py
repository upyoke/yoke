"""Run the harness passes from onboarding, reporting instead of raising.

Onboarding writes the unattended posture and the machine-wide hooks as named
steps among many, so a harness config it cannot write leaves a machine that
still prompts or runs without Yoke hooks outside a project — not a broken
install. Each failure is reported into the onboarding report, with its
recovery, and the run continues.
"""

from __future__ import annotations

import io
from typing import Any, List

from yoke_contracts.harness_machine_hooks import (
    MACHINE_HOOKS_PLAN_ACTION,
    installed_machine_hooks,
)
from yoke_contracts.harness_posture_install import (
    configure_harness_unattended_posture,
)
from yoke_cli.config import onboard_apply_progress


def apply_reported() -> List[str]:
    """Write the posture into every detected harness; never raise."""
    try:
        return configure_harness_unattended_posture(stream=io.StringIO())
    except Exception as exc:  # noqa: BLE001 — reported, never fatal
        return [f"harness posture was not written: {exc}"]


def apply_machine_hooks(
    progress: onboard_apply_progress.ProgressCallback | None,
    report: dict[str, Any],
) -> None:
    """Install machine-wide hooks for every installed harness; never raise."""
    from yoke_harness.hooks.machine_hooks import (
        MACHINE_HOOKS_NOT_WRITTEN,
        ensure_machine_hooks_reported,
    )

    specs = installed_machine_hooks()
    for spec in specs:
        onboard_apply_progress.emit(
            progress, MACHINE_HOOKS_PLAN_ACTION, spec.display_path(), "running"
        )
    lines, failures = ensure_machine_hooks_reported([spec.harness_id for spec in specs])
    report["machine_hooks"] = lines
    for spec in specs:
        # A failure line names its harness; a whole-run refusal names none.
        failed = any(
            line.startswith((f"{spec.harness_id}: ", MACHINE_HOOKS_NOT_WRITTEN))
            for line in failures
        )
        onboard_apply_progress.emit(
            progress, MACHINE_HOOKS_PLAN_ACTION, spec.display_path(), "failed" if failed else "done"
        )


__all__ = ["apply_machine_hooks", "apply_reported"]
