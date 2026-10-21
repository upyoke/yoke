"""Probe each installed supported shell without borrowing the installer's PATH."""

from __future__ import annotations

import shutil
from pathlib import Path


def diagnose_contexts(env: dict, directories: tuple[str, ...]) -> tuple[dict, ...]:
    from yoke_cli.config import path_doctor as doctor

    rows = []
    for shell in doctor.SUPPORTED_SHELLS:
        executable = (
            env.get("SHELL")
            if Path(env.get("SHELL", "")).name == shell
            else shutil.which(shell, path=env.get("PATH"))
        )
        if not executable:
            continue
        selected = {**env, "SHELL": executable}
        for context, flag in (
            ("login", "-lc"),
            ("interactive", "-ic"),
            ("non-login", "-c"),
            ("ssh", "-c"),
        ):
            if context == "ssh":
                resolved = doctor.verify_ssh_command(
                    shell, env=selected, managed_path_dirs=directories
                )
            else:
                resolved = doctor._verify_shell(
                    flag,
                    shell,
                    env=selected,
                    managed_path_dirs=directories,
                    child_shell=context == "non-login" and shell == "bash",
                )
            by_name = {row.name: row.path for row in resolved}
            shadow = doctor._shadowing_yoke_path(
                resolved, bindir=doctor.tool_bin_dir(selected)
            )
            rows.append(
                {
                    "shell": shell,
                    "context": context,
                    "resolved": by_name,
                    "needs_fix": not by_name.get("yoke") or bool(shadow),
                    "reason": "shell_path_unresolved"
                    if not by_name.get("yoke")
                    else ("shell_path_shadowed" if shadow else ""),
                    "recovery": "Run `yoke path fix --yes`; open a new terminal and check shell files that override PATH.",
                }
            )
    return tuple(rows)
