"""Session-bound workspace helpers used by ``session_dispatch``.

Owns the surface that exports ``YOKE_BOUND_WORKSPACE`` to the harness
env-file at SessionStart so subsequent Bash invocations inherit the
session's anchored workspace. The env var is the defense-in-depth pin
consumed by the writer guard in
``yoke_core.domain.agents_render._atomic_write`` and the cross-checkout
PreToolUse lint in ``yoke_core.domain.lint_workspace_cwd_match``.

Lives in the hook_runner subpackage because ``session_dispatch.py`` is at
the file-line cap (ticket addendum) and the workspace export needs a
sibling module to absorb new logic without busting the cap.
"""

from __future__ import annotations

import os
import shlex


BOUND_WORKSPACE_ENV_VAR = "YOKE_BOUND_WORKSPACE"


def _export_line(workspace: str) -> str:
    return f"export {BOUND_WORKSPACE_ENV_VAR}={shlex.quote(workspace)}\n"


def persist_bound_workspace_to_env_file(workspace: str, env_file: str) -> bool:
    """Append ``export YOKE_BOUND_WORKSPACE=<workspace>`` to ``env_file`` once.

    Mirrors the existing ``persist_session_id_to_env_file`` shape: idempotent
    re-runs of SessionStart are no-ops once the line is present with the
    current workspace, and any stale value is replaced. OSError on the
    env-file write is swallowed (the env var is defense in depth, not a
    primary surface). Returns True on success or already-present; False on
    missing inputs or write failure.
    """
    if not workspace or not env_file:
        return False
    desired = _export_line(workspace)
    try:
        lines: list[str] = []
        if os.path.isfile(env_file):
            with open(env_file, encoding="utf-8") as handle:
                lines = handle.readlines()
            if desired in lines:
                return True
            lines = [
                line for line in lines
                if f"{BOUND_WORKSPACE_ENV_VAR}=" not in line
            ]
        lines.append(desired)
        with open(env_file, "w", encoding="utf-8") as handle:
            handle.writelines(lines)
        return True
    except OSError:
        return False


def export_bound_workspace_for_session(workspace: str, env_file: str = "") -> bool:
    """Set the env var in the running process AND persist to the env file.

    The in-process ``os.environ`` set covers tools that re-enter the runner
    process (subprocess invocations spawned from the same Python interpreter
    inherit env from os.environ). The env-file write covers Claude Code's
    next Bash tool invocation, which sources the env file before exec.
    """
    if not workspace:
        return False
    os.environ[BOUND_WORKSPACE_ENV_VAR] = workspace
    if env_file:
        return persist_bound_workspace_to_env_file(workspace, env_file)
    return True


__all__ = [
    "BOUND_WORKSPACE_ENV_VAR",
    "persist_bound_workspace_to_env_file",
    "export_bound_workspace_for_session",
]
