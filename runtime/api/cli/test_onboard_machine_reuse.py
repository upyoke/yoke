"""Review keeps already-current machine hooks, relay and skill off the changes."""

from __future__ import annotations

from pathlib import Path

from yoke_cli.config import harness_posture_install, onboard_global_skill
from yoke_cli.config import onboard_machine_reuse, onboard_project, onboard_report
from yoke_cli.config import onboard_reuse_feedback, onboard_reuse_state
from yoke_cli.config import onboard_session_relay
from yoke_contracts.global_skill_install import ensure_global_skill
from yoke_contracts.harness_machine_hooks import MACHINE_HOOKS_PLAN_ACTION

_REAL_RELAY_SATISFIED = onboard_machine_reuse.relay_satisfied
_CONFIG = Path("/home/.yoke/config.json")
_RELAY_ACTIONS = {
    step["action"]
    for step in onboard_session_relay.plan_steps(
        local_destination=False, config_path=_CONFIG, environment="prod"
    )
}


def _home(tmp_path):
    return tmp_path / "harness-home"  # the conftest-isolated home


def _review(monkeypatch, *, relay_current: bool) -> tuple[set[str], list[str]]:
    """Detect reuse the way setup does, then build the plan Review renders."""
    monkeypatch.setattr(
        onboard_machine_reuse,
        "relay_satisfied",
        lambda *, cfg_path, env_name: relay_current,
    )
    project_inputs = {"mode": onboard_project.PROJECT_MODE_MACHINE_ONLY}
    credential = {"kind": "token_file", "path": "/home/.yoke/secrets/prod.token"}
    reuse = onboard_reuse_state.detect(
        cfg_path=_CONFIG,
        env_name="prod",
        api_url="https://api.test",
        credential_source=credential,
        source=credential,
        project_inputs=project_inputs,
        machine_github={"choice": "skip"},
    )
    plan = onboard_report.build_plan(
        _CONFIG,
        "prod",
        "https://api.test",
        credential,
        credential,
        "quick",
        project_mode=onboard_project.PROJECT_MODE_MACHINE_ONLY,
        project_inputs=project_inputs,
        machine_github={"choice": "skip"},
        reuse=reuse,
    )
    actions = {step["action"] for step in plan["steps"]}
    kept = onboard_reuse_feedback.grouped_lines_for_plan(plan)["machine"]
    return actions, kept


def test_first_setup_lists_hooks_relay_and_skill_as_changes(tmp_path, monkeypatch):
    (_home(tmp_path) / ".claude").mkdir(parents=True)
    actions, kept = _review(monkeypatch, relay_current=False)
    assert MACHINE_HOOKS_PLAN_ACTION in actions
    assert _RELAY_ACTIONS <= actions
    assert onboard_global_skill.INSTALL_ACTION in actions
    assert not [line for line in kept if "hooks" in line or "relay" in line]


def test_rerun_on_a_set_up_machine_keeps_them_as_reuse(tmp_path, monkeypatch):
    (_home(tmp_path) / ".claude").mkdir(parents=True)
    (_home(tmp_path) / ".cursor").mkdir(parents=True)
    harness_posture_install.apply_reported()
    assert not ensure_global_skill().refused

    actions, kept = _review(monkeypatch, relay_current=True)

    assert MACHINE_HOOKS_PLAN_ACTION not in actions
    assert not _RELAY_ACTIONS & actions
    assert onboard_global_skill.INSTALL_ACTION not in actions
    assert (
        "Yoke's machine-wide hooks are already current in ~/.claude/settings.json."
        in kept
    )
    assert (
        "Yoke's machine-wide hooks are already current in ~/.cursor/hooks.json."
        in kept
    )
    assert "The machine relay is already installed and running." in kept
    assert "The yoke-global skill is already installed." in kept


def test_a_stale_skill_is_still_a_change(tmp_path, monkeypatch):
    (_home(tmp_path) / ".claude").mkdir(parents=True)
    assert not ensure_global_skill().refused
    skill = _home(tmp_path) / ".agents" / "skills" / "yoke-global" / "SKILL.md"
    skill.write_text("an older skill body\n")

    actions, kept = _review(monkeypatch, relay_current=True)

    assert onboard_global_skill.INSTALL_ACTION in actions
    assert "The yoke-global skill is already installed." not in kept


def test_relay_reuse_is_the_relay_installers_status(monkeypatch):
    calls = []

    def status(**kwargs):
        calls.append(kwargs)
        return True

    monkeypatch.setattr(onboard_session_relay, "is_supported", lambda **kw: True)
    monkeypatch.setattr(onboard_session_relay, "is_satisfied", status)
    assert _REAL_RELAY_SATISFIED(cfg_path=_CONFIG, env_name="prod")
    assert calls == [{"config_path": _CONFIG, "environment": "prod"}]

    monkeypatch.setattr(onboard_session_relay, "is_satisfied", lambda **kw: False)
    assert not _REAL_RELAY_SATISFIED(cfg_path=_CONFIG, env_name="prod")
