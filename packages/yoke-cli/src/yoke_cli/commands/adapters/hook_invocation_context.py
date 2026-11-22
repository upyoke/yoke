"""Root, identity and owner context a Windows hook command passes as options.

The Windows hook command is a bare ``yoke hook evaluate <Verb> --harness
<id> [--config-owner <owner>]`` so cmd, PowerShell and Git Bash all run it
without a wrapper shell. This module sets what the POSIX ``/bin/sh`` form sets
in its ``env`` prefix, before anything reads ``os.environ`` or the cwd.
"""

from __future__ import annotations

import os
import re
from collections.abc import MutableMapping
from pathlib import Path

from yoke_contracts.hook_runner.config_owner import (
    CONFIG_OWNER_ENV_VAR,
    CURSOR_USER_CONFIG_OWNER,
)

#: The variable each harness sets to the session folder; Codex sets none,
#: so its root is ``YOKE_ROOT`` from the session or the hook's cwd.
HOOK_ROOT_VARIABLES = {
    "claude-code": "CLAUDE_PROJECT_DIR",
    "codex": "YOKE_ROOT",
    "cursor": "CURSOR_PROJECT_DIR",
}

# Codex and Cursor hook subprocesses do not reliably carry a harness signal.
_IDENTITY_ENV = {
    "claude-code": {},
    "codex": {"YOKE_EXECUTOR": "codex", "YOKE_PROVIDER": "openai"},
    "cursor": {"YOKE_EXECUTOR": "cursor"},
}

# Cursor lifecycle hooks can outlive a deleted lane, and its user hooks spawn
# from ~/.cursor, so those pick an existing root and enter it.
_CURSOR_WALK_VERBS = frozenset({"Stop", "SessionEnd"})
_LANE_SUFFIX = re.compile(r"[\\/]\.(?:claude[\\/])?worktrees[\\/].*$")


def _cwd() -> str:
    try:
        return os.getcwd()
    except OSError:  # A deleted cwd; the walk or the payload cwd decides.
        return ""


def _existing_root(environ: MutableMapping[str, str]) -> str:
    candidates = [
        environ.get("YOKE_ROOT", ""),
        environ.get("CURSOR_PROJECT_DIR", ""),
        _cwd(),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_dir():
            return candidate
    for candidate in candidates:
        parent = _LANE_SUFFIX.sub("", candidate)
        if parent and Path(parent).is_dir():
            return parent
    return str(Path.home())


def apply_hook_invocation_context(
    harness_id: str | None,
    verb: str,
    config_owner: str | None,
    environ: MutableMapping[str, str],
) -> None:
    """Set ``YOKE_ROOT``, identity and owner for one hook invocation.

    Without ``--harness`` the command came from the POSIX form, whose ``env``
    prefix already set all of it.
    """
    if harness_id is None:
        return
    if harness_id == "cursor" and (
        verb in _CURSOR_WALK_VERBS or config_owner == CURSOR_USER_CONFIG_OWNER
    ):
        root = _existing_root(environ)
        os.chdir(root)
    else:
        root = environ.get(HOOK_ROOT_VARIABLES[harness_id]) or _cwd()
    if root:
        environ["YOKE_ROOT"] = root
    environ.update(_IDENTITY_ENV[harness_id])
    if config_owner:
        environ[CONFIG_OWNER_ENV_VAR] = config_owner


__all__ = ["HOOK_ROOT_VARIABLES", "apply_hook_invocation_context"]
