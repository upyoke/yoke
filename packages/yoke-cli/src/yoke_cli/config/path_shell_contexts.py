"""Probe each installed supported shell without borrowing the installer's PATH."""

from __future__ import annotations

import shutil
from pathlib import Path


def _recovery(shell: str, context: str, env: dict, winner: str | None,
              expected: str, error: str) -> str:
    from yoke_cli.config.path_state_contract import (
        default_startup_file, startup_files_for_shell,
    )

    home = Path(env["HOME"])
    if shell == "bash":
        files = [home / ".bashrc"] if context in ("interactive", "ssh") else [
            default_startup_file(shell, home), home / ".bashrc",
        ]
        if env.get("BASH_ENV") and context in ("non-login", "ssh"):
            files.append(Path(env["BASH_ENV"]))
    elif shell == "zsh":
        files = startup_files_for_shell(shell, Path(env.get("ZDOTDIR") or home))
    else:
        files = [Path(env.get("XDG_CONFIG_HOME") or home / ".config")
                 / "fish" / "config.fish"]
    inspect = "Inspect " + ", ".join(map(str, files)) + " and files they source. "
    if error:
        return inspect + "Fix the shell startup failure, then rerun `yoke path verify`."
    if winner and winner != expected:
        return (inspect + f"Remove or reorder the competing PATH entry for {Path(winner).parent} "
                f"so {Path(expected).parent} comes first; open a new terminal and run "
                "`yoke path verify`. Yoke repairs only its owned PATH blocks.")
    return (inspect + f"If {expected} is missing, reinstall Yoke; otherwise correct later PATH "
            "overrides manually, then open a new terminal and run `yoke path verify`.")


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
            error = next((row.error for row in resolved if row.error), "")
            rows.append(
                {
                    "shell": shell,
                    "context": context,
                    "resolved": by_name,
                    "needs_fix": not by_name.get("yoke") or bool(shadow),
                    "reason": error or "shell_path_unresolved"
                    if not by_name.get("yoke")
                    else ("shell_path_shadowed" if shadow else ""),
                    "recovery": _recovery(
                        shell, context, selected, by_name.get("yoke"),
                        str(Path(doctor.tool_bin_dir(selected)) / "yoke"), error,
                    ) if not by_name.get("yoke") or shadow else "",
                }
            )
    return tuple(rows)
