"""Apply machine-local runtime directories, posture, relay, and registry."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Mapping

from yoke_contracts import harness_unattended_posture
from yoke_cli.config import harness_posture_install
from yoke_cli.config import machine_config
from yoke_cli.config import onboard_apply_progress
from yoke_cli.config import onboard_machine_registry
from yoke_cli.config import onboard_session_relay
from yoke_cli.config import writer


BROWSER_SETUP_ACTION = "browser-setup"
BROWSER_SETUP_TARGET = "machine"


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
    runtime_steps = tuple(
        step
        for step in (
            None if reuse.get("temp_root") else ("create-runtime-dir", "temp_root"),
            None if reuse.get("cache_dir") else ("create-runtime-dir", "cache_dir"),
        )
        if step is not None
    )
    if runtime_steps:
        onboard_apply_progress.emit_many(progress, runtime_steps, "running")
        writer.set_runtime_paths(
            temp_root=config_path.parent / "tmp",
            cache_dir=config_path.parent / "cache",
            path=config_path,
        )
        Path(machine_config.temp_root(config_path)).mkdir(parents=True, exist_ok=True)
        machine_config.cache_dir(config_path).mkdir(parents=True, exist_ok=True)
        onboard_apply_progress.emit_many(progress, runtime_steps, "done")
    _setup_browser(progress, report, error_cls=error_cls)
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


def _setup_browser(progress, report, *, error_cls=RuntimeError):
    if sys.platform.startswith("linux"):
        onboard_apply_progress.emit(
            progress, BROWSER_SETUP_ACTION, BROWSER_SETUP_TARGET, "running"
        )
        try:
            from yoke_harness.browser_setup import ensure_browser_runtime
            from yoke_harness.python_venv_dependencies import ensure_venv_support

            ensure_venv_support(emit=lambda line: print(line, file=sys.stderr))
            ensure_browser_runtime(emit=lambda line: print(line, file=sys.stderr))
        except (ImportError, OSError, RuntimeError) as exc:
            onboard_apply_progress.emit(
                progress, BROWSER_SETUP_ACTION, BROWSER_SETUP_TARGET, "failed"
            )
            raise error_cls(str(exc)) from exc
        report["browser_setup"] = {"status": "ready"}
        onboard_apply_progress.emit(
            progress, BROWSER_SETUP_ACTION, BROWSER_SETUP_TARGET, "done"
        )


__all__ = ["apply"]
