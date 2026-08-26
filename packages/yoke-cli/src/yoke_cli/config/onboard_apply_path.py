"""Apply and verify the PATH writes previewed by onboarding Review."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from yoke_cli.config import onboard_apply_progress
from yoke_cli.config import onboard_path_plan
from yoke_cli.config import path_doctor
from yoke_cli.config import path_repair_plan


def _resolutions(rows: list[path_doctor.ToolResolution]) -> dict[str, str | None]:
    return {row.name: row.path for row in rows}


def apply(
    plan: dict[str, Any] | None,
    *,
    progress: onboard_apply_progress.ProgressCallback | None,
    report: dict[str, Any],
) -> None:
    if not plan:
        return
    directories = tuple(str(path) for path in plan.get("directories", []))
    changed_files = []
    applied_files = []
    for target in plan.get("targets", []):
        path = Path(str(target["path"]))
        onboard_apply_progress.emit(
            progress, onboard_path_plan.PATH_REPAIR_ACTION, str(path), "running"
        )
        if path_doctor.apply_fix(path, directories):
            changed_files.append(str(path))
        applied_files.append(str(path))
        onboard_apply_progress.emit(
            progress, onboard_path_plan.PATH_REPAIR_ACTION, str(path), "done"
        )

    shell = str(plan.get("shell") or "") or None
    login = path_doctor.verify_fresh_login(shell, managed_path_dirs=directories)
    ssh = path_doctor.verify_ssh_command(shell, managed_path_dirs=directories)
    report["path_repair"] = {
        **plan,
        "applied_files": applied_files,
        "changed_files": changed_files,
        "login_verified": path_repair_plan.verification_ok(login, plan),
        "ssh_verified": path_repair_plan.verification_ok(ssh, plan),
        "login_resolved": _resolutions(login),
        "ssh_resolved": _resolutions(ssh),
    }


__all__ = ["apply"]
