"""Apply uv shell setup and verify the real fresh login shell."""

from __future__ import annotations
from typing import Any
from yoke_cli.config import (
    onboard_apply_progress,
    onboard_path_plan,
    path_doctor,
    path_repair_plan,
)


def apply(
    plan: dict[str, Any] | None,
    *,
    progress: onboard_apply_progress.ProgressCallback | None,
    report: dict[str, Any],
) -> None:
    if not plan:
        return
    output = ""
    if plan.get("targets"):
        target = path_repair_plan.UPDATE_SHELL_COMMAND
        onboard_apply_progress.emit(
            progress, onboard_path_plan.PATH_REPAIR_ACTION, target, "running"
        )
        output = path_doctor.update_shell()
        onboard_apply_progress.emit(
            progress, onboard_path_plan.PATH_REPAIR_ACTION, target, "done"
        )
    login = path_doctor.verify_fresh_login(str(plan.get("shell") or "") or None)
    report["path_repair"] = {
        **plan,
        "output": output,
        "login_verified": path_repair_plan.verification_ok(login, plan),
        "login_resolved": {row.name: row.path for row in login},
    }
