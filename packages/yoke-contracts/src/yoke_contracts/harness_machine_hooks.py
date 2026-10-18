"""Where each harness reads user-level hooks, and which events Yoke puts there.

Yoke's machine-wide hooks live in each harness's user config so a session
opened outside any Yoke project still registers, receives messages and runs
the machine-scope Bash guards. Inside a project the project's own hooks own
the event, and the user-level invocation steps aside (``yoke hook evaluate``
reads ``project_configs`` before evaluating anything).

This module is the single source for those facts. The renderer copies each
entry into ``runtime/harness/<dir>/manifest.json`` under ``machine_hooks``
(documented in ``runtime/harness/manifest-machine-hooks.md``); the installer,
the step-aside rule, uninstall and doctor read it from here.

The event set is light on purpose: session lifecycle, prompt delivery and the
PreToolUse Bash chain that carries the machine guards. Every other event
carries only project or lane guards, per-tool heartbeat or telemetry, so it
stays project-only.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

from yoke_contracts.hook_runner.config_owner import (
    CLAUDE_USER_CONFIG_OWNER,
    CODEX_USER_CONFIG_OWNER,
    CURSOR_USER_CONFIG_OWNER,
)


#: The user-level hooks-file trust a harness requires before running it.
TrustKind = Literal["none", "codex_trusted_hash"]

#: Retired machine-hook markers. Install and uninstall delete entries that
#: carry one; nothing reads them for any other purpose.
RETIRED_USER_HOOK_MARKERS: tuple[str, ...] = (
    "YOKE_CURSOR_LIFECYCLE_ROOT=1",
    "yoke-cursor-stop-canary",
)


@dataclass(frozen=True)
class MachineHookEvent:
    """One native event Yoke writes into the user config."""

    native_event: str
    verb: str
    matcher: Optional[str] = None

    def to_json(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "native_event": self.native_event,
            "verb": self.verb,
        }
        if self.matcher is not None:
            payload["matcher"] = self.matcher
        return payload


@dataclass(frozen=True)
class HarnessMachineHooks:
    """One harness's user-level hook location, events and install rules."""

    harness_id: str
    home: str
    home_env: str
    user_config: str
    config_owner: str
    project_configs: tuple[str, ...]
    # True: the harness reads project configs in every folder from the session
    # folder up to the repository root; False: only the folder it opened.
    project_config_in_ancestors: bool
    events: tuple[MachineHookEvent, ...]
    trust: TrustKind
    deferrals: tuple[str, ...] = ()

    def home_path(self, environ: Optional[Mapping[str, str]] = None) -> Path:
        """The harness home; its absence means the harness is not installed."""
        env = os.environ if environ is None else environ
        override = env.get(self.home_env) if self.home_env else None
        if override:
            return Path(override).expanduser()
        base = env.get("HOME") or str(Path.home())
        return Path(base) / self.home.removeprefix("~/")

    def user_config_path(self, environ: Optional[Mapping[str, str]] = None) -> Path:
        return self.home_path(environ) / self.user_config

    def trust_config_path(self, environ: Optional[Mapping[str, str]] = None) -> Path:
        """The user config under its resolved folder, as Codex keys trust.

        Codex resolves a symlinked home before matching ``trusted_hash``
        entries (measured on codex-cli 0.161.0 with a /tmp home), so trust
        minted under the literal path would never match.
        """
        path = self.user_config_path(environ)
        return path.parent.resolve() / path.name

    def display_path(self) -> str:
        """The user config path as written to a person."""
        return f"{self.home}/{self.user_config}"

    def native_events_for(self, verb: str) -> tuple[str, ...]:
        return tuple(e.native_event for e in self.events if e.verb == verb)

    def to_json(self) -> dict[str, object]:
        return {
            "user_config_path": self.display_path(),
            "home_env": self.home_env or None,
            "config_owner": self.config_owner,
            "project_configs": list(self.project_configs),
            "project_config_in_ancestors": self.project_config_in_ancestors,
            "events": [event.to_json() for event in self.events],
            "trust": self.trust,
            "deferrals": list(self.deferrals),
        }


HARNESS_MACHINE_HOOKS: Mapping[str, HarnessMachineHooks] = {
    "claude-code": HarnessMachineHooks(
        harness_id="claude-code",
        home="~/.claude",
        home_env="",
        user_config="settings.json",
        config_owner=CLAUDE_USER_CONFIG_OWNER,
        project_configs=(".claude/settings.json", ".claude/settings.local.json"),
        project_config_in_ancestors=False,
        events=(
            MachineHookEvent("SessionStart", "SessionStart"),
            MachineHookEvent("UserPromptSubmit", "UserPromptSubmit"),
            MachineHookEvent("PreToolUse", "PreToolUse", "Bash"),
            MachineHookEvent("Stop", "Stop"),
            MachineHookEvent("SessionEnd", "SessionEnd"),
        ),
        trust="none",
    ),
    "codex": HarnessMachineHooks(
        harness_id="codex",
        home="~/.codex",
        home_env="CODEX_HOME",
        user_config="hooks.json",
        config_owner=CODEX_USER_CONFIG_OWNER,
        project_configs=(".codex/hooks.json",),
        project_config_in_ancestors=True,
        events=(
            MachineHookEvent("SessionStart", "SessionStart", "startup|resume"),
            MachineHookEvent("UserPromptSubmit", "UserPromptSubmit"),
            MachineHookEvent("PreToolUse", "PreToolUse", "Bash"),
            MachineHookEvent("Stop", "Stop"),
        ),
        trust="codex_trusted_hash",
        deferrals=(
            "SessionEnd: codex-cli 0.161.0 fires a SessionEnd hook, but Yoke's "
            "Codex project hooks do not wire it; the machine-wide set matches "
            "the project set so one Yoke evaluation runs per native event.",
        ),
    ),
    "cursor": HarnessMachineHooks(
        harness_id="cursor",
        home="~/.cursor",
        home_env="",
        user_config="hooks.json",
        config_owner=CURSOR_USER_CONFIG_OWNER,
        project_configs=(".cursor/hooks.json",),
        project_config_in_ancestors=False,
        events=(
            MachineHookEvent("sessionStart", "SessionStart"),
            MachineHookEvent("beforeSubmitPrompt", "UserPromptSubmit"),
            MachineHookEvent("beforeShellExecution", "PreToolUse"),
            MachineHookEvent("stop", "Stop"),
            MachineHookEvent("sessionEnd", "SessionEnd"),
        ),
        trust="none",
    ),
}

#: Config owner value -> harness, for the step-aside rule.
HARNESS_BY_USER_OWNER: Mapping[str, str] = {
    spec.config_owner: harness_id for harness_id, spec in HARNESS_MACHINE_HOOKS.items()
}


def entry_commands(entry: object) -> list[str]:
    """Commands in a flat (Cursor) or nested (Claude, Codex) hook entry."""
    if not isinstance(entry, Mapping):
        return []
    commands = [entry["command"]] if isinstance(entry.get("command"), str) else []
    nested = entry.get("hooks")
    if isinstance(nested, list):
        commands.extend(
            hook["command"]
            for hook in nested
            if isinstance(hook, Mapping) and isinstance(hook.get("command"), str)
        )
    return commands


#: The setup plan step that installs the machine-wide hooks, one per harness.
MACHINE_HOOKS_PLAN_ACTION = "install-machine-hooks"


def installed_machine_hooks(
    environ: Optional[Mapping[str, str]] = None,
) -> list[HarnessMachineHooks]:
    """Harnesses whose home exists on this machine."""
    return [spec for spec in HARNESS_MACHINE_HOOKS.values() if spec.home_path(environ).is_dir()]


def machine_hooks_plan_steps() -> list[dict[str, str]]:
    """Setup review entries naming each user config the install writes."""
    return [
        {"action": MACHINE_HOOKS_PLAN_ACTION, "target": spec.display_path()}
        for spec in installed_machine_hooks()
    ]


def machine_hooks_for_harness(harness_id: str) -> HarnessMachineHooks:
    try:
        return HARNESS_MACHINE_HOOKS[harness_id]
    except KeyError:
        raise ValueError(f"no machine hooks declared for harness {harness_id!r}")


__all__ = [
    "HARNESS_BY_USER_OWNER",
    "HARNESS_MACHINE_HOOKS",
    "HarnessMachineHooks",
    "MACHINE_HOOKS_PLAN_ACTION",
    "MachineHookEvent",
    "RETIRED_USER_HOOK_MARKERS",
    "entry_commands",
    "installed_machine_hooks",
    "machine_hooks_for_harness",
    "machine_hooks_plan_steps",
]
