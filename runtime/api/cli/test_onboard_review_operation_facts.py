"""Review describes applicable writes, prior effects and native launch posture."""

import io
import json
import tomllib

import pytest

from yoke_cli.config import onboard_plan_labels as labels
from yoke_cli.config import onboard_post_checkout_plan as checkout_plan
from yoke_cli.config import onboard_project, onboard_wizard_plan_review as review
from yoke_cli.config import onboard_wizard_review_steps as steps
from yoke_cli.config.onboard_permission_review import permission_summary
from yoke_contracts import harness_unattended_posture as posture
from yoke_contracts.claude_posture_install import configure_claude_app_bypass_permissions
from yoke_contracts.codex_hook_trust_store import mint_installed_checkout_trust
from yoke_contracts.harness_folder_trust_grant import grant_folder_trust
from yoke_contracts.session_control import launch_permission_bypass as bypass


@pytest.fixture
def machine(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "custom-codex"))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    return tmp_path


@pytest.mark.parametrize("platform", ["linux", "darwin"])
@pytest.mark.parametrize("desktop_present", [False, True])
def test_desktop_disclosure_matches_applicability(machine, monkeypatch, platform, desktop_present):
    monkeypatch.setattr(posture.sys, "platform", platform)
    (machine / ".claude").mkdir()
    desktop = posture.claude_config_path()
    if desktop_present:
        desktop.parent.mkdir(parents=True)
        desktop.write_text("{}")
    summary = posture.posture_plan_summary()
    assert (str(desktop) in summary) == desktop_present
    assert configure_claude_app_bypass_permissions(stream=io.StringIO()) == desktop_present
    assert desktop.exists() == desktop_present


def test_codex_review_paths_and_keys_match_real_project_writes(machine):
    config = posture.codex_config_path()
    config.parent.mkdir()
    config.write_text('approval_policy = "on-request"\nsandbox_mode = "read-only"\n')
    checkout = machine / "project"
    hooks = checkout / ".codex/hooks.json"
    hooks.parent.mkdir(parents=True)
    hooks.write_text(json.dumps({"hooks": {"SessionStart": [{"hooks": [
        {"type": "command", "command": "yoke hook evaluate SessionStart"}
    ]}]}}))
    planned = checkout_plan.post_checkout_steps(
        onboard_project.PROJECT_MODE_LOCAL_CHECKOUT,
        {"checkout": str(checkout)}, reuse={},
    )
    hook_step = next(row for row in planned if row["action"] == "project-install-harness-hooks")
    line = labels.friendly_line(hook_step["action"], hook_step["target"])
    assert str(hooks) in line
    assert str(config) in line
    assert "trusted_hash" in line and "trust_level" in line
    grant_folder_trust(checkout, harnesses=("codex",))
    result = mint_installed_checkout_trust(checkout)
    assert result.changed
    parsed = tomllib.loads(config.read_text())
    assert parsed["projects"][str(checkout)]["trust_level"] == "trusted"
    assert parsed["approval_policy"] == "on-request"
    assert parsed["sandbox_mode"] == "read-only"
    assert "trusted_hash" in config.read_text()
    summary = posture.posture_plan_summary()
    assert str(config) in summary
    assert str(config.parent / "rules/yoke.rules") in summary


def test_absent_codex_does_not_promise_machine_trust_writes(machine):
    line = labels.friendly_line("project-install-harness-hooks", "/project")
    assert "no machine config or hook-trust writes" in line
    assert "codex:" not in posture.posture_plan_summary()


def test_worker_disclosure_matches_native_declarations():
    compact = permission_summary(expanded=False)
    assert len(compact) == 1
    assert "sandbox" in compact[0] and "hook-trust" in compact[0]
    expanded = "\n".join(permission_summary(expanded=True))
    for harness in ("claude-code", "codex", "cursor"):
        for argument in bypass.cli_bypass_arguments(harness):
            assert argument in expanded
    for key, value in bypass.codex_thread_bypass_parameters().items():
        assert f"{key}={value}" in expanded


def test_summary_stays_compact_and_expansion_has_complete_facts(machine):
    config = posture.codex_config_path()
    config.parent.mkdir()
    plan = {"plan": {"steps": [
        {"action": "set-active-env", "target": "prod"},
        {"action": "project-install-harness-hooks", "target": "/project"},
    ]}}
    summary = "\n".join(str(widget.render()) for widget in review.render_plan_summary(plan))
    expanded = "\n".join(str(widget.render()) for widget in review.render_write_plan(plan))
    assert "2 changes" in summary and "Machine:" in summary and "Project:" in summary
    assert str(config) not in summary
    assert str(config) in expanded and "trusted_hash" in expanded
    assert steps.review_rows(plan, [], False, False)[1].label == "Show all changes"
    assert steps.review_rows(plan, [], False, True)[1].label == "Show summary"


def test_review_distinguishes_prior_path_writes(machine):
    plan = {"plan": {"path_repair": {"changed_files": ["/home/user/.profile"],
                                     "login_verified": True},
                     "steps": [{"action": "set-active-env", "target": "prod"}]}}
    prompt = steps.review_prompt(plan, step="finish", problems=[], notes=[],
                                 machine_github_saved=False, show_all=False, status_lines=[])
    assert "already" in prompt.subtitle and "PATH" in prompt.subtitle
    assert "Cancel keeps" in prompt.subtitle
    assert all("update-shell-path" not in line for line in prompt.detail_lines)


def test_prior_shell_file_inventory_stays_behind_show_all(monkeypatch):
    from types import SimpleNamespace
    from yoke_cli.config import onboard_wizard_finish_flow as finish

    monkeypatch.setattr(finish, "machine_finish_lines", lambda _result: [])
    flow = finish.FinishBodyFlow()
    flow.result = SimpleNamespace(
        path_repair={"changed_files": ["/home/person/.profile"]},
        yoke_token_verification=None, hosting_verification=None,
    )
    assert flow._review_status_lines() == []
    flow._review_show_all = True
    assert any("/home/person/.profile" in line for line in flow._review_status_lines())
