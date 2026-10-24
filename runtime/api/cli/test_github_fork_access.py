"""Fork readiness names actual cached topology and gates Review and Apply."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from yoke_cli.config import github_fork_access as access
from yoke_cli.config import machine_config, onboard_preflight, project_onboard_clone
from yoke_cli.config import onboard_wizard_github_state as state
from yoke_cli.config.project_clone_support import ClonePlan
from yoke_cli.config.project_onboard_support import ProjectOnboardError

SOURCE = "https://github.com/source/widgets.git"


@pytest.fixture
def topology():
    return {
        "authorization": {"login": "owner"},
        "installations": [
            {"installation_id": 1, "account_type": "User", "account_login": "owner",
             "repository_selection": "all", "permissions": {"contents": "write", "administration": "write"}},
            {"installation_id": 2, "account_type": "Organization", "account_login": "source",
             "repository_selection": "selected", "permissions": {"contents": "read", "administration": "write"}},
        ],
        "repositories": [{"full_name": "source/widgets", "installation_id": 2}],
    }


def test_healthy_topology_is_ready(topology):
    assert access.unavailable_reason(topology, SOURCE) == ""
    assert state.fork_ready_from_config(topology, SOURCE)


@pytest.mark.parametrize("change,reason", [
    ("selected", "fork_destination_access_unavailable"),
    ("source", "fork_source_access_unavailable"),
    ("suspended", "fork_source_access_unavailable"),
    ("contents", "fork_source_access_unavailable"),
    ("administration", "fork_source_access_unavailable"),
])
def test_unavailable_reason_names_actual_condition(topology, change, reason):
    if change == "selected":
        topology["installations"][0]["repository_selection"] = "selected"
    elif change == "source":
        topology["repositories"] = []
    elif change == "suspended":
        topology["installations"][1]["suspended"] = True
    else:
        topology["installations"][1]["permissions"][change] = "none"
    problem = access.unavailable_reason(topology, SOURCE)
    assert problem.startswith(reason)
    assert "yoke github connect" in problem
    assert "baseline" not in problem
    assert "does not request" not in problem
    assert not state.fork_ready_from_config(topology, SOURCE)
    if change == "selected":
        assert "All repositories" in problem
        assert "fork_source_access_unavailable" not in problem
    else:
        assert "source/widgets" in problem
        assert "fork_destination_access_unavailable" not in problem


def result():
    return SimpleNamespace(
        project_mode="local-checkout", project_clone_outcome="fork",
        project_remote_url=SOURCE, config_path="/unused/config.json",
        project_checkout=None, project_github_repo="source/widgets",
        machine_github_choice="connect", machine_github_verification={"ok": True, "ready": True},
    )


def test_review_and_apply_share_cached_reason_after_topology_changes(topology, monkeypatch, tmp_path):
    current = deepcopy(topology)
    monkeypatch.setattr(machine_config, "github_config", lambda *a: current)
    selected = result()
    assert not onboard_preflight.preflight(selected).problems
    current["installations"][0]["repository_selection"] = "selected"
    reason = access.unavailable_reason(current, SOURCE)
    assert onboard_preflight.preflight(selected).problems == [reason]
    plan = project_onboard_clone.prepare_clone_plan(
        ClonePlan(outcome="fork", fallback_token="fixture-only"), None, remote_url=SOURCE,
    )
    assert plan.fork_unavailable_reason == reason
    with pytest.raises(ProjectOnboardError) as error:
        project_onboard_clone.apply_clone_outcome(tmp_path, remote_url=SOURCE, default_branch="main", plan=plan)
    assert str(error.value) == reason


def test_apply_uses_installations_refreshed_with_token(topology, monkeypatch):
    current = deepcopy(topology)
    current["repositories"] = []
    monkeypatch.setattr(machine_config, "github_config", lambda *a: current)

    def refresh(**kwargs):
        current.update(deepcopy(topology))
        return SimpleNamespace(access_token="fixture-only")

    monkeypatch.setattr(project_onboard_clone.github_local_user_access, "access_token", refresh)
    plan = project_onboard_clone.prepare_clone_plan(
        ClonePlan(outcome="fork", use_machine_github=True), None, remote_url=SOURCE,
    )
    assert plan.fork_allowed is True
    assert plan.fork_unavailable_reason == ""


@pytest.mark.parametrize("surface", ["wizard", "agent"])
def test_explicit_fork_preset_cannot_offer_apply_when_unavailable(topology, monkeypatch, tmp_path, surface):
    from yoke_cli.config.onboard_wizard import WizardDefaults
    from yoke_cli.config.onboard_wizard_app import OnboardWizardApp
    from yoke_cli.config.setup_agent_shell import AgentSetup
    from yoke_cli.config.setup_agent_answers import AnswerStore

    monkeypatch.setattr(machine_config, "github_config", lambda *a: topology)
    topology["installations"][0]["repository_selection"] = "selected"
    defaults = WizardDefaults(
        config_path=str(tmp_path / "config.json"), project_mode="local-checkout",
        project_clone_outcome="fork", api_url="https://test.invalid", destination="hosted",
    )
    options = {"defaults": defaults, "apply_report": lambda *a, **k: {
        "plan": {"steps": [{"action": "project-fork-remotes", "target": SOURCE}]},
    }}
    shell = (
        OnboardWizardApp(**options) if surface == "wizard" else
        AgentSetup(**options, store=AnswerStore({}, existed=False), cli_answers={})
    )
    views = []
    shell._goto = views.append
    shell.result.project_remote_url = SOURCE
    shell.result.project_github_repo = "source/widgets"
    shell.result.machine_github_choice = "connect"
    shell.result.machine_github_verification = {"ok": True, "ready": True}
    shell._goto_clone_outcome()
    assert shell.result.project_clone_outcome == "fork"
    model = shell._build_review_model()
    reason = access.unavailable_reason(topology, SOURCE)
    assert model["checks"].problems == [reason]
    shell._show_finish(model)
    prompt = views[-1].prompt
    assert "apply" not in [choice.value for choice in prompt.choices]
    assert reason in " ".join(prompt.detail_lines)
