"""Report shared harness setup to onboarding without stopping other steps."""

from __future__ import annotations

from yoke_harness.harness_setup_reconcile import reconcile_harness_setup
from yoke_cli.config import onboard_apply_progress
from yoke_contracts.harness_machine_hooks import (
    MACHINE_HOOKS_PLAN_ACTION,
    installed_machine_hooks,
)


def apply_reported(*, include_posture: bool = True, progress=None) -> list[str]:
    """Reconcile all registered targets and name every outcome and recovery."""
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
    return result.lines()


__all__ = ["apply_reported"]
