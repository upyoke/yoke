"""Apply owned shell setup and verify every supported shell context."""

from __future__ import annotations
import os
from pathlib import Path
from typing import Any
from yoke_cli.config import (
    onboard_apply_progress,
    onboard_path_plan,
    path_doctor,
    path_repair_plan,
)

# Keep a newly created file distinguishable from an unreadable snapshot.
_MISSING = object()


def _snapshot(path: Path) -> object:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return _MISSING
    except OSError:
        return None


def apply(
    plan: dict[str, Any] | None,
    *,
    progress: onboard_apply_progress.ProgressCallback | None,
    report: dict[str, Any],
) -> None:
    if not plan:
        return
    if plan.get("login_verified"):
        report["path_repair"] = dict(plan)
        return
    output = ""
    report["path_repair"] = {**plan, "login_verified": False}
    home = Path.home()
    files = set(path_doctor.supported_startup_files(home))
    if os.environ.get("ZDOTDIR"):
        files.update(
            path_doctor.startup_files_for_shell("zsh", Path(os.environ["ZDOTDIR"]))
        )
    if os.environ.get("XDG_CONFIG_HOME"):
        files.add(Path(os.environ["XDG_CONFIG_HOME"]) / "fish" / "config.fish")
    if plan.get("targets"):
        before = {path: _snapshot(path) for path in files}
        target = path_repair_plan.UPDATE_SHELL_COMMAND
        onboard_apply_progress.emit(
            progress, onboard_path_plan.PATH_REPAIR_ACTION, target, "running"
        )
        try:
            output = path_doctor.update_shell()
        finally:
            report["path_repair"]["changed_files"] = sorted(
                str(path)
                for path, content in before.items()
                if content is not None
                and (after := _snapshot(path)) is not None
                and after != content
            )
        onboard_apply_progress.emit(
            progress, onboard_path_plan.PATH_REPAIR_ACTION, target, "done"
        )
    diagnosis = path_doctor.diagnose()
    login = path_doctor.verify_fresh_login(str(plan.get("shell") or "") or None)
    report["path_repair"] = {
        **report["path_repair"],
        "output": output,
        "login_verified": not diagnosis.needs_fix,
        "contexts": list(diagnosis.contexts),
        "login_resolved": {row.name: row.path for row in login},
    }
