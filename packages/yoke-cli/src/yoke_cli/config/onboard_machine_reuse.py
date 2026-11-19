"""Machine-wide setup that is already current, so Review keeps it off the changes.

Every setup run converges the machine-wide hooks, the machine relay and the
``yoke-global`` skill. When a run finds them already current, Review names
them under "Already on this machine" instead of listing them as changes. Each
judgement belongs to the owner that installs it: the read-only machine-hooks
inspection, the relay installer's ``status`` and the global-skill readiness
check. Apply still converges all three; finding them current writes nothing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from yoke_cli.config import onboard_session_relay
from yoke_contracts import harness_machine_hooks
from yoke_contracts.global_skill_install import global_skill_ready
from yoke_contracts.harness_global_skill import HARNESS_GLOBAL_SKILLS

MACHINE_HOOKS = "machine_hooks"
SESSION_RELAY = "session_relay"
GLOBAL_SKILL = "global_skill"


def detect(*, cfg_path: Path, env_name: str) -> dict[str, Any]:
    """Reuse facts for the machine-wide setup every run converges."""
    return {
        MACHINE_HOOKS: current_machine_hook_targets(),
        SESSION_RELAY: relay_satisfied(cfg_path=cfg_path, env_name=env_name),
        GLOBAL_SKILL: global_skill_current(),
    }


def current_machine_hook_targets() -> list[str]:
    """Display paths of the harness configs whose machine hooks are installed."""
    from yoke_harness.hooks.machine_hooks_inspect import (
        STATE_INSTALLED,
        inspect_machine_hooks,
    )

    current = {
        result.harness_id
        for result in inspect_machine_hooks()
        if result.outcome == STATE_INSTALLED
    }
    return [
        spec.display_path()
        for spec in harness_machine_hooks.installed_machine_hooks()
        if spec.harness_id in current
    ]


def relay_satisfied(*, cfg_path: Path, env_name: str) -> bool:
    """Whether the relay installer reports this connection's relay as current."""
    if not onboard_session_relay.is_supported(local_destination=False):
        return False
    return onboard_session_relay.is_satisfied(
        config_path=cfg_path, environment=env_name
    )


def global_skill_current() -> bool:
    """Whether every installed harness already discovers the current skill."""
    installed = [
        harness_id
        for harness_id in HARNESS_GLOBAL_SKILLS
        if harness_machine_hooks.machine_hooks_for_harness(harness_id)
        .home_path()
        .is_dir()
    ]
    return bool(installed) and all(
        global_skill_ready(harness_id)[0] for harness_id in installed
    )


def machine_hook_steps(reuse: Mapping[str, Any]) -> list[dict[str, str]]:
    """Review steps for each harness config whose machine hooks need writing."""
    current = set(reuse.get(MACHINE_HOOKS) or ())
    return [
        {
            "action": harness_machine_hooks.MACHINE_HOOKS_PLAN_ACTION,
            "target": spec.display_path(),
        }
        for spec in harness_machine_hooks.installed_machine_hooks()
        if spec.display_path() not in current
    ]


def reuse_lines(reuse: Mapping[str, Any]) -> list[str]:
    """The "Already on this machine" lines for machine-wide setup kept as is."""
    lines = [
        f"Yoke's machine-wide hooks are already current in {target}."
        for target in reuse.get(MACHINE_HOOKS) or ()
    ]
    if reuse.get(SESSION_RELAY):
        lines.append("The machine relay is already installed and running.")
    if reuse.get(GLOBAL_SKILL):
        lines.append("The yoke-global skill is already installed.")
    return lines


__all__ = [
    "GLOBAL_SKILL",
    "MACHINE_HOOKS",
    "SESSION_RELAY",
    "current_machine_hook_targets",
    "detect",
    "global_skill_current",
    "machine_hook_steps",
    "relay_satisfied",
    "reuse_lines",
]
