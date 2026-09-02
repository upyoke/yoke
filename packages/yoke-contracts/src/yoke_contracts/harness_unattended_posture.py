"""The persistent config each harness needs so `yoke` never asks permission.

Yoke's own launched workers already run unattended: the launch plane passes
each harness its bypass flag, declared once in
:mod:`yoke_contracts.session_control.launch_permission_bypass`. A session a
*person* opens gets none of that — it reads whatever the harness has
persisted on the machine, and every harness ships defaults that stop and ask.
The result is a stranger who installs Yoke, opens a harness, and is asked to
approve each ``yoke`` call, including the field-note command Yoke tells them
to run when something goes wrong.

So the same posture is written into each harness's own machine config at
install time. This module says what "unattended" means per harness, taking
the values from the launch contract wherever it already states them, so the
launched and the operator-opened session cannot drift apart.

Grounded against the builds this repository supports:

* ``codex`` — ``$CODEX_HOME/config.toml``: ``approval_policy`` and
  ``sandbox_mode``, plus a ``[projects."<checkout>"]`` trust entry so the
  harness does not ask about the directory itself. Codex has no project-local
  config file it reads, so this is the only place the posture can live.
* ``cursor`` — ``~/.cursor/cli-config.json``: ``approvalMode`` and
  ``sandbox.mode``. ``unrestricted`` is the persisted form of the mode the
  CLI calls Run Everything (``--force`` / ``--yolo``); ``allowlist`` is the
  prompting default.
* ``claude-code`` — ``claude_desktop_config.json``:
  ``preferences.bypassPermissionsModeEnabled``.

Writing these is a real widening of what a harness will run without asking,
which is why each install pass says out loud what it changed and a health
check reports the standing posture rather than assuming it.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised on the older interpreter only
    import tomli as tomllib

from yoke_contracts.executor_labels import CANONICAL_HARNESS_IDS
from yoke_contracts.session_control.launch_permission_bypass import (
    CODEX_APPROVAL_POLICY,
    CODEX_SANDBOX_MODE,
)

CLAUDE_FAMILY, CODEX_FAMILY, CURSOR_FAMILY = CANONICAL_HARNESS_IDS

#: Environment variable naming the Codex configuration home.
CODEX_HOME_ENV = "CODEX_HOME"

#: Codex config keys carrying the unattended posture, with the values it needs.
CODEX_APPROVAL_POLICY_KEY = "approval_policy"
CODEX_SANDBOX_MODE_KEY = "sandbox_mode"
CODEX_POSTURE_KEYS: Tuple[Tuple[str, str], ...] = (
    (CODEX_APPROVAL_POLICY_KEY, CODEX_APPROVAL_POLICY),
    (CODEX_SANDBOX_MODE_KEY, CODEX_SANDBOX_MODE),
)

#: Codex's per-directory trust table, and the value that stops it asking.
CODEX_PROJECTS_TABLE = "projects"
CODEX_TRUST_LEVEL_KEY = "trust_level"
CODEX_TRUST_LEVEL = "trusted"

#: Cursor's machine config and the two keys that decide whether it prompts.
CURSOR_CLI_CONFIG_PATH = "~/.cursor/cli-config.json"
CURSOR_APPROVAL_MODE_KEY = "approvalMode"
CURSOR_APPROVAL_MODE = "unrestricted"
CURSOR_SANDBOX_CONTAINER = "sandbox"
CURSOR_SANDBOX_MODE_KEY = "mode"
CURSOR_SANDBOX_MODE = "disabled"

#: Claude's app config and the preference that decides whether it prompts.
CLAUDE_APP_CONFIG_PATH = (
    "~/Library/Application Support/Claude/claude_desktop_config.json"
)
CLAUDE_BYPASS_KEY = "bypassPermissionsModeEnabled"


@dataclass(frozen=True)
class PostureFinding:
    """One harness's standing posture, as a reader can report it."""

    harness_id: str
    config_path: str
    #: ``None`` when the harness is not set up on this machine at all.
    present: bool
    unattended: bool
    problems: Tuple[str, ...] = ()

    def summary(self) -> str:
        if not self.present:
            return f"{self.harness_id}: not set up on this machine"
        if self.unattended:
            return f"{self.harness_id}: unattended ({self.config_path})"
        return f"{self.harness_id}: prompts — {'; '.join(self.problems)}"


def codex_config_path() -> Path:
    """Resolve the Codex config file this machine reads.

    Codex keeps approval policy, sandbox mode, directory trust, and hook
    trust in one machine-level file; it reads no project-local config.
    """
    home = os.environ.get(CODEX_HOME_ENV)
    root = Path(home) if home else Path.home() / ".codex"
    return root / "config.toml"


def cursor_config_path() -> Path:
    """Resolve the Cursor CLI config file this machine reads."""
    return Path(CURSOR_CLI_CONFIG_PATH).expanduser()


def claude_config_path() -> Path:
    """Resolve the Claude app config file this machine reads."""
    return Path(CLAUDE_APP_CONFIG_PATH).expanduser()


def codex_project_trust_key(checkout: str | Path) -> str:
    """Return the ``projects`` sub-table key naming one checkout."""
    return str(Path(checkout).expanduser())


def codex_posture_problems(config: Mapping[str, Any]) -> Tuple[str, ...]:
    """Name every Codex posture key that still leaves the harness prompting."""
    problems = []
    for key, wanted in CODEX_POSTURE_KEYS:
        current = config.get(key)
        if current != wanted:
            problems.append(f"{key} is {current!r}, not {wanted!r}")
    return tuple(problems)


def cursor_posture_problems(config: Mapping[str, Any]) -> Tuple[str, ...]:
    """Name every Cursor posture key that still leaves the harness prompting."""
    problems = []
    if config.get(CURSOR_APPROVAL_MODE_KEY) != CURSOR_APPROVAL_MODE:
        problems.append(
            f"{CURSOR_APPROVAL_MODE_KEY} is "
            f"{config.get(CURSOR_APPROVAL_MODE_KEY)!r}, not "
            f"{CURSOR_APPROVAL_MODE!r}"
        )
    sandbox = config.get(CURSOR_SANDBOX_CONTAINER)
    sandbox = sandbox if isinstance(sandbox, dict) else {}
    if sandbox.get(CURSOR_SANDBOX_MODE_KEY) != CURSOR_SANDBOX_MODE:
        problems.append(
            f"{CURSOR_SANDBOX_CONTAINER}.{CURSOR_SANDBOX_MODE_KEY} is "
            f"{sandbox.get(CURSOR_SANDBOX_MODE_KEY)!r}, not "
            f"{CURSOR_SANDBOX_MODE!r}"
        )
    return tuple(problems)


def claude_posture_problems(config: Mapping[str, Any]) -> Tuple[str, ...]:
    """Name the Claude preference that still leaves the harness prompting."""
    prefs = config.get("preferences")
    prefs = prefs if isinstance(prefs, dict) else {}
    if prefs.get(CLAUDE_BYPASS_KEY) is not True:
        return (
            f"preferences.{CLAUDE_BYPASS_KEY} is "
            f"{prefs.get(CLAUDE_BYPASS_KEY)!r}, not True",
        )
    return ()


#: What one harness's standing posture reads as. ``ABSENT`` is not a pass:
#: a harness that is not installed has no posture to report either way.
POSTURE_UNATTENDED = "unattended"
POSTURE_PROMPTS = "prompts"
POSTURE_ABSENT = "absent"


def read_posture_config(
    harness_id: str, path: Optional[Path] = None,
) -> Tuple[Optional[Dict[str, Any]], str]:
    """Parsed config for one harness, or ``(None, reason)`` when unreadable.

    A file that does not parse yields ``None`` with its reason rather than an
    empty mapping: the harness reads no posture from it either, so calling it
    configured would invert the answer.
    """
    target = path if path is not None else managed_config_paths()[harness_id]
    if not target.parent.is_dir():
        return None, f"no {harness_id} config directory at {target.parent}"
    if not target.is_file():
        return None, f"no {harness_id} config at {target}"
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"{target} could not be read ({exc})"
    try:
        parsed = tomllib.loads(text) if target.suffix == ".toml" else json.loads(text)
    except ValueError as exc:
        return None, f"{target} does not parse ({exc})"
    return (parsed if isinstance(parsed, dict) else {}), ""


def posture_state(harness_id: str, path: Optional[Path] = None) -> str:
    """Report one harness's standing posture as a single word."""
    config, _reason = read_posture_config(harness_id, path)
    if config is None:
        return POSTURE_ABSENT
    return POSTURE_PROMPTS if posture_problems(harness_id, config) else (
        POSTURE_UNATTENDED
    )


#: One recovery line, shared by every surface that reports a prompting harness.
POSTURE_RECOVERY = (
    "Repair: `python3 -m yoke_core.tools.install_yoke_launcher --repair` "
    "writes the unattended posture into each detected harness's own config, "
    "leaving your other settings in place."
)


def posture_problems(harness_id: str, config: Mapping[str, Any]) -> Tuple[str, ...]:
    """Dispatch to the reader for one harness family."""
    readers = {
        CODEX_FAMILY: codex_posture_problems,
        CURSOR_FAMILY: cursor_posture_problems,
        CLAUDE_FAMILY: claude_posture_problems,
    }
    try:
        return readers[harness_id](config)
    except KeyError as exc:
        raise ValueError(f"unknown harness id: {harness_id!r}") from exc


def sandbox_recovery(harness_id: Optional[str] = None) -> Optional[str]:
    """Recovery for a command a harness sandbox refused, or ``None``.

    ``None`` covers both "not running under a harness" and "under one whose
    posture Yoke does not manage", so a caller can append this without first
    having to know which harness it is.
    """
    if harness_id is None:
        from yoke_contracts.harness_family_identity import nearest_harness_family

        try:
            harness_id = nearest_harness_family()
        except Exception:  # noqa: BLE001 — identity must never raise here
            return None
    if str(harness_id or "").strip() not in CANONICAL_HARNESS_IDS:
        return None
    return (
        f"A {harness_id} session runs commands under its own approval and "
        f"sandbox policy, which blocks Yoke's control plane until the "
        f"unattended posture is written. {POSTURE_RECOVERY}"
    )


def managed_config_paths() -> Dict[str, Path]:
    """Machine config file each managed harness reads its posture from."""
    return {
        CODEX_FAMILY: codex_config_path(),
        CURSOR_FAMILY: cursor_config_path(),
        CLAUDE_FAMILY: claude_config_path(),
    }


__all__ = [
    "CLAUDE_APP_CONFIG_PATH",
    "CLAUDE_BYPASS_KEY",
    "CODEX_APPROVAL_POLICY_KEY",
    "CODEX_HOME_ENV",
    "CODEX_POSTURE_KEYS",
    "CODEX_PROJECTS_TABLE",
    "CODEX_SANDBOX_MODE_KEY",
    "CODEX_TRUST_LEVEL",
    "CODEX_TRUST_LEVEL_KEY",
    "CURSOR_APPROVAL_MODE",
    "CURSOR_APPROVAL_MODE_KEY",
    "CURSOR_CLI_CONFIG_PATH",
    "CURSOR_SANDBOX_CONTAINER",
    "CURSOR_SANDBOX_MODE",
    "CURSOR_SANDBOX_MODE_KEY",
    "POSTURE_ABSENT",
    "POSTURE_PROMPTS",
    "POSTURE_RECOVERY",
    "POSTURE_UNATTENDED",
    "PostureFinding",
    "claude_config_path",
    "claude_posture_problems",
    "managed_config_paths",
    "codex_config_path",
    "codex_posture_problems",
    "codex_project_trust_key",
    "cursor_config_path",
    "cursor_posture_problems",
    "posture_problems",
    "posture_state",
    "read_posture_config",
    "sandbox_recovery",
]
