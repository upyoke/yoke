"""Report shared harness setup to onboarding without stopping other steps."""

from __future__ import annotations

from typing import TYPE_CHECKING
from yoke_cli.config import onboard_apply_progress
from yoke_contracts.harness_machine_hooks import (
    MACHINE_HOOKS_PLAN_ACTION,
    installed_machine_hooks,
)

if TYPE_CHECKING:
    from yoke_harness.harness_setup_reconcile import HarnessSetupResult


def apply_reported(
    *, include_posture: bool = True, progress=None
) -> HarnessSetupResult:
    """Reconcile all registered targets and name every outcome and recovery."""
    from yoke_harness.harness_setup_reconcile import reconcile_harness_setup

    specs = installed_machine_hooks()
    for spec in specs:
        onboard_apply_progress.emit(
            progress, MACHINE_HOOKS_PLAN_ACTION, spec.display_path(), "running"
        )
    result = reconcile_harness_setup(include_posture=include_posture)
    for spec in specs:
        failed = any(
            row.harness_id == spec.harness_id
            and row.facet == "machine_hooks"
            and row.outcome in ("failed", "refused")
            for row in result.rows
        )
        onboard_apply_progress.emit(
            progress,
            MACHINE_HOOKS_PLAN_ACTION,
            spec.display_path(),
            "failed" if failed else "done",
        )
    return result


__all__ = ["apply_reported"]
