"""Report the process PATH and the persistent Windows user PATH separately."""

from __future__ import annotations

import shutil
from pathlib import Path

from yoke_contracts.shell_path_state import PATH_TOOLS, tool_bin_dir
from yoke_contracts.windows_user_path import (
    USER_PATH_LOCATION,
    contains,
    fresh_path,
    normalized,
    read_user_path,
)


def resolve_tools(value: str):
    from yoke_cli.config.path_doctor import ToolResolution

    return [ToolResolution(tool, shutil.which(tool, path=value)) for tool in PATH_TOOLS]


def diagnose_windows(env: dict[str, str], *, home: Path | None = None):
    from yoke_cli.config.path_doctor import PathDiagnosis
    from yoke_cli.config.path_harness_clis import resolve_harness_clis

    if home is not None:
        env = dict(env, HOME=str(home))
    directory = tool_bin_dir(env)
    current = env.get("PATH", "")
    user = read_user_path()
    future = fresh_path(env)

    present, later = resolve_tools(current), resolve_tools(future)
    preferred = str(Path(directory) / "yoke.cmd")

    def shadowed(rows):
        winner = next(row.path for row in rows if row.name == "yoke")
        return (
            winner
            if winner and normalized(winner, env) != normalized(preferred, env)
            else ""
        )

    future_shadow = shadowed(later)
    missing = not next(row.path for row in later if row.name == "yoke")
    needs_fix = not contains(user, directory, env) or missing or bool(future_shadow)
    return PathDiagnosis(
        current_shell="windows",
        tool_bin_dir=directory,
        current_on_path=contains(current, directory, env),
        current_resolved=present,
        startup_file=USER_PATH_LOCATION,
        future_adds_bin=contains(user, directory, env),
        managed_block_present=False,
        future_resolved=later,
        needs_fix=needs_fix or bool(shadowed(present)),
        login_needs_fix=needs_fix,
        preferred_yoke_path=preferred,
        yoke_shadowed_by=shadowed(present),
        future_yoke_shadowed_by=future_shadow,
        managed_path_dirs=(directory,),
        harness_clis=resolve_harness_clis(current),
        contexts=(
            {
                "shell": "windows",
                "context": "user-path",
                "startup_files": [USER_PATH_LOCATION],
                "path": user,
                "needs_fix": needs_fix,
                "resolved": {row.name: row.path for row in later},
                "reason": "windows_user_path_unresolved" if needs_fix else "",
                "recovery": "Run yoke path fix --yes, open a new terminal, then run yoke path doctor.",
            },
        ),
    )
