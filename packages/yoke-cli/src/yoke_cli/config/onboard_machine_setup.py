"""Deterministic machine preparation before onboarding asks for choices."""

from __future__ import annotations

from pathlib import Path
import sys

from yoke_contracts.machine_config import reader as machine_config
from yoke_cli.config import machine_config_file, onboard_apply_progress

BROWSER_SETUP_ACTION = "browser-setup"
BROWSER_SETUP_TARGET = "machine"
RUNTIME_DIRECTORY_NAMES = {"temp_root": "tmp", "cache_dir": "cache"}


def directory_paths(config_path: Path) -> dict[str, Path]:
    """Find runtime directories beside the selected config unless it names others."""
    config = machine_config.load_config(config_path)
    return {
        key: config_path.parent / Path(config.get(key) or name).expanduser()
        for key, name in RUNTIME_DIRECTORY_NAMES.items()
    }


def directory_readiness(config_path: Path) -> dict[str, bool]:
    return {key: path.is_dir() for key, path in directory_paths(config_path).items()}


def setup_directories(config_path: Path, *, reuse=None, progress=None) -> None:
    if reuse is not None and all(reuse.get(key) for key in RUNTIME_DIRECTORY_NAMES):
        return
    paths = directory_paths(config_path)
    steps = tuple(
        ("create-runtime-dir", key)
        for key, path in paths.items()
        if not (path.is_dir() if reuse is None else reuse.get(key))
    )
    if not steps:
        return
    onboard_apply_progress.emit_many(progress, steps, "running")
    machine_config_file.ensure_owner_only_directory(config_path.parent)
    for _, key in steps:
        paths[key].mkdir(parents=True, exist_ok=True)
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
