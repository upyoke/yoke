"""Apply machine-local runtime directories, posture, relay, and registry."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from yoke_contracts import harness_unattended_posture
from yoke_cli.config import harness_posture_install
from yoke_cli.config import onboard_machine_setup
from yoke_cli.config import onboard_apply_progress
from yoke_cli.config import onboard_machine_registry
from yoke_cli.config import onboard_session_relay


def apply(
    *,
    config_path: Path,
    reuse: Mapping[str, Any],
    harness_posture: bool,
    progress: onboard_apply_progress.ProgressCallback | None,
    report: dict[str, Any],
    local_destination: bool,
    environment: str,
    error_cls=RuntimeError,
) -> None:
    onboard_machine_setup.setup_directories(config_path, reuse=reuse, progress=progress)
    onboard_machine_setup.setup_wsl(report, error_cls=error_cls)
    onboard_machine_setup.setup_browser(progress, report, error_cls=error_cls)
    if harness_posture:
        step = (harness_unattended_posture.POSTURE_PLAN_ACTION, "detected")
        onboard_apply_progress.emit(progress, *step, "running")
        report["harness_unattended_posture"] = harness_posture_install.apply_reported()
        onboard_apply_progress.emit(progress, *step, "done")
    onboard_session_relay.apply(
        progress,
        report,
        local_destination=local_destination,
        config_path=config_path,
        environment=environment,
    )
    onboard_machine_registry.apply(config_path, progress=progress, report=report)


__all__ = ["apply"]
