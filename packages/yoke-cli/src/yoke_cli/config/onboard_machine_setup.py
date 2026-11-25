"""Deterministic machine preparation before onboarding asks for choices."""

from __future__ import annotations

from pathlib import Path
import sys

from yoke_contracts.machine_config import reader as machine_config
from yoke_cli.config import machine_config_file, onboard_apply_progress

BROWSER_SETUP_ACTION = "browser-setup"
BROWSER_SETUP_TARGET = "machine"
RUNTIME_PATHS = {"temp_root": machine_config.temp_root, "cache_dir": machine_config.cache_dir}


def directory_readiness(config_path: Path) -> dict[str, bool]:
    return {
        key: Path(getter(config_path)).is_dir()
        for key, getter in RUNTIME_PATHS.items()
    }


def setup_directories(config_path: Path, *, reuse=None, progress=None) -> None:
    reuse = directory_readiness(config_path) if reuse is None else reuse
    steps = tuple(
        ("create-runtime-dir", key)
        for key in RUNTIME_PATHS
        if not reuse.get(key)
    )
    if not steps:
        return
    onboard_apply_progress.emit_many(progress, steps, "running")
    machine_config_file.ensure_owner_only_directory(config_path.parent)
    for _, key in steps:
        Path(RUNTIME_PATHS[key](config_path)).mkdir(parents=True, exist_ok=True)
    onboard_apply_progress.emit_many(progress, steps, "done")


def setup_browser(progress, report, *, error_cls=RuntimeError):
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


def setup_wsl(report, *, error_cls=RuntimeError):
    from yoke_contracts.wsl import is_wsl

    if not is_wsl():
        return
    try:
        from yoke_harness.wsl_systemd import setup

        status = setup(emit=lambda line: print(line, file=sys.stderr))
    except (OSError, RuntimeError) as exc:
        raise error_cls(str(exc)) from exc
    report["wsl_setup"] = {"status": status}


def prepare(config_path: Path) -> dict:
    """Failures are advisory here; Apply rechecks and repairs the same steps."""
    report = {}
    steps = (
        ("runtime directories", lambda: setup_directories(config_path)),
        ("browser and Python runtime", lambda: setup_browser(None, report)),
    )
    for name, work in steps:
        print(f"Preparing {name}…", file=sys.stderr)
        try:
            work()
        except Exception as exc:  # noqa: BLE001 - reaching the wizard is unconditional
            print(
                f"onboard_machine_setup_failed ({name}): {exc}. Continuing to the wizard; Apply will retry.",
                file=sys.stderr,
            )
        else:
            print(f"Ready: {name}.", file=sys.stderr)
    return report
