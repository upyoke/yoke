"""What a person's interactive Claude session needs to pass Yoke's posture check.

``yoke doctor run --session`` passes a Claude session only when its
parent-session hook reports ``bypassPermissions``. Setup persists that mode
as ``permissions.defaultMode`` in ``~/.claude/settings.json``
(:mod:`yoke_contracts.claude_posture_install`). This module holds the facts
about how Claude Code treats that default and what a person can do when a
session is not in it, so the doctor recovery, the uninstall revert and the
rendered manifest (``session_permission_posture`` in
``runtime/harness/claude/manifest.json``) read one declaration.

Grounded against Claude Code's permission-mode documentation (checked
2026-11-17 against v2.1.327, https://code.claude.com/docs/en/permission-modes):

* ``bypassPermissions`` enters a session only when it is enabled at launch:
  ``permissions.defaultMode`` in user, managed or ``--settings`` settings,
  ``--permission-mode bypassPermissions`` or
  ``--dangerously-skip-permissions``. Shift+Tab cycles Manual, Accept edits
  and Plan, then optional modes; bypass permissions is in that cycle only
  when enabled at launch, so a session started without it cannot reach it.
* From v2.1.283 the built-in default for terminal and VS Code sessions is
  ``auto``. On Pro, Max, Ultra and Team plans Claude Code asks once whether
  to change a ``defaultMode`` other than ``auto`` to ``auto``; accepting
  rewrites Yoke's ``bypassPermissions`` to ``auto``. That value exists only
  because Yoke wrote its default, so uninstall reverts it like Yoke's own
  write, and the CLI recovery restores the default and starts a new session
  (Claude Code does not ask again).
* The first interactive bypass session shows a warning dialog; accepting it
  makes Claude Code write ``skipDangerousModePermissionPrompt: true`` to the
  same file. Yoke never writes that acceptance, but it records the key's
  absence so uninstall removes the acceptance its own default caused.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional

from yoke_contracts.session_control.launch_permission_bypass import (
    CLAUDE_SETTINGS_PERMISSION_MODE,
    CLAUDE_SETTINGS_PERMISSION_MODE_KEY,
)

CLAUDE_SETTINGS_DISPLAY_PATH = "~/.claude/settings.json"
CLAUDE_DEFAULT_MODE_SETTING = f"permissions.{CLAUDE_SETTINGS_PERMISSION_MODE_KEY}"

#: Values Claude Code substitutes for Yoke's persisted default on its own.
CLAUDE_DEFAULT_MODE_REWRITES: tuple[str, ...] = ("auto",)

#: Key Claude Code writes when a person accepts the bypass warning dialog.
CLAUDE_BYPASS_ACCEPTANCE_KEY = "skipDangerousModePermissionPrompt"

CLAUDE_BYPASS_LAUNCH_COMMAND = (
    f"claude --permission-mode {CLAUDE_SETTINGS_PERMISSION_MODE}"
)

_RERUN = "send any prompt, then rerun `yoke doctor run --session`"


@dataclass(frozen=True)
class SessionPermissionPosture:
    """One harness's required session mode and how a person reaches it."""

    harness_id: str
    session_mode: str
    default_setting: str
    default_setting_path: str
    default_rewrites: tuple[str, ...]
    harness_acceptance_key: str
    launch_command: str
    in_session_switch: str
    surface_recovery: Mapping[str, str]
    default_lost_recovery: str
    evidence: str

    def recovery(self, surface_id: str, *, default_mode: Optional[str]) -> str:
        """The action this surface can take, given the persisted default."""
        if surface_id == "claude-cli" and default_mode != self.session_mode:
            return self.default_lost_recovery
        return self.surface_recovery[surface_id]

    def unavailable(self, surface_id: str, *, default_mode: Optional[str]) -> tuple:
        """Remedies that look relevant but this state forbids."""
        if surface_id == "claude-cli" and default_mode != self.session_mode:
            return (
                f"{self.in_session_switch} cannot reach bypass permissions: this "
                f"session started with {self.default_setting} = {default_mode!r}",
            )
        return ()

    def to_json(self) -> dict:
        return {
            "source": (
                "yoke_contracts.harness_session_permission_posture."
                "CLAUDE_SESSION_PERMISSION_POSTURE"
            ),
            "session_mode": self.session_mode,
            "default_setting": self.default_setting,
            "default_setting_path": self.default_setting_path,
            "default_rewrites": list(self.default_rewrites),
            "harness_acceptance_key": self.harness_acceptance_key,
            "launch_command": self.launch_command,
            "in_session_switch": self.in_session_switch,
            "surface_recovery": dict(self.surface_recovery),
            "default_lost_recovery": self.default_lost_recovery,
            "evidence": self.evidence,
        }


CLAUDE_SESSION_PERMISSION_POSTURE = SessionPermissionPosture(
    harness_id="claude-code",
    session_mode=CLAUDE_SETTINGS_PERMISSION_MODE,
    default_setting=CLAUDE_DEFAULT_MODE_SETTING,
    default_setting_path=CLAUDE_SETTINGS_DISPLAY_PATH,
    default_rewrites=CLAUDE_DEFAULT_MODE_REWRITES,
    harness_acceptance_key=CLAUDE_BYPASS_ACCEPTANCE_KEY,
    launch_command=CLAUDE_BYPASS_LAUNCH_COMMAND,
    in_session_switch="Shift+Tab",
    surface_recovery={
        "claude-cli": (
            "press Shift+Tab until the mode reads bypass permissions, "
            f"{_RERUN}; if it is not in the cycle, exit and start "
            f"`{CLAUDE_BYPASS_LAUNCH_COMMAND}`"
        ),
        "claude-desktop": (
            f"select Bypass permissions in this chat's mode selector, {_RERUN}"
        ),
        "claude-vscode": (
            "turn on Allow dangerously skip permissions in the Claude Code "
            "extension settings, start a new conversation, select bypass "
            f"permissions in its mode indicator, {_RERUN}"
        ),
    },
    default_lost_recovery=(
        "run `yoke doctor run --only harness-setup --fix` to set "
        f"{CLAUDE_DEFAULT_MODE_SETTING} in {CLAUDE_SETTINGS_DISPLAY_PATH} back "
        f"to {CLAUDE_SETTINGS_PERMISSION_MODE}, exit this session, start "
        f"`claude` again (or `{CLAUDE_BYPASS_LAUNCH_COMMAND}`), accept the "
        f"bypass permissions warning, {_RERUN}"
    ),
    evidence=(
        "Claude Code docs checked 2026-11-17 (v2.1.327): bypassPermissions is "
        "reachable only when enabled at launch; Shift+Tab includes it only "
        "then. Claude Code asks once to change a non-auto defaultMode to auto "
        "and rewrites the setting when accepted, and records "
        "skipDangerousModePermissionPrompt when its bypass warning is accepted. "
        "https://code.claude.com/docs/en/permission-modes"
    ),
)


__all__ = [
    "CLAUDE_BYPASS_ACCEPTANCE_KEY",
    "CLAUDE_BYPASS_LAUNCH_COMMAND",
    "CLAUDE_DEFAULT_MODE_REWRITES",
    "CLAUDE_DEFAULT_MODE_SETTING",
    "CLAUDE_SESSION_PERMISSION_POSTURE",
    "CLAUDE_SETTINGS_DISPLAY_PATH",
    "SessionPermissionPosture",
]
