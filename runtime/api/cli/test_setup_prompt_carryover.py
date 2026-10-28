"""Information-only setup transitions reach real questions in both shells."""

import pytest
from textual.widgets import Static

from runtime.api.cli.setup_agent_test_support import git_checkout, isolate_agent_setup
from yoke_cli.config import onboard_project, setup_agent_response
from yoke_cli.config.onboard_wizard import WizardDefaults
from yoke_cli.config.onboard_wizard_app import OnboardWizardApp
from yoke_cli.config.onboard_wizard_flows import init_setup_state
from yoke_cli.config.onboard_wizard_state import _View
from yoke_cli.config.setup_agent_shell import AgentSetup
from yoke_cli.config.setup_prompt import SelectionRow, SetupPrompt


@pytest.fixture(params=[OnboardWizardApp, AgentSetup], ids=["wizard", "agent"])
def shell(request, tmp_path, monkeypatch):
    apply = isolate_agent_setup(tmp_path, monkeypatch)
    defaults = WizardDefaults(config_path=str(tmp_path / "config.json"))
    if request.param is OnboardWizardApp:
        result = OnboardWizardApp(defaults=defaults, apply_report=apply)
    else:
        result = object.__new__(AgentSetup)
        init_setup_state(result, defaults=defaults, apply_report=apply)
    # Inspect the common view graph without mounting a terminal or answering it.
    monkeypatch.setattr(result, "_render_current", lambda: None)
    result._permission_disclosed = True
    return result


def test_existing_folder_reaches_project_details_without_a_stop(shell, tmp_path):
    checkout = git_checkout(tmp_path / "project")
    shell.result.project_mode = onboard_project.PROJECT_MODE_CREATE_REPO

    shell._after_checkout(str(checkout))

    prompt = shell._history[-1].prompt
    assert prompt.key == "project.details"
    assert shell.result.project_mode == onboard_project.PROJECT_MODE_LOCAL_CHECKOUT
    assert "That folder already exists." in prompt.detail_lines
    assert f"Yoke will set up {checkout} as an existing project instead of creating a new one." in prompt.detail_lines
    assert "project.folder_exists" not in [view.prompt.key for view in shell._history]
    assert "That folder already exists." in setup_agent_response.question_fields(prompt)["detail"]


def test_github_connection_reaches_next_question_with_repository_advice(shell):
    report = {
        "ok": True, "ready": True, "configured": True,
        "identity": {"login": "octocat"},
        "access": {"installations": [{
            "account_login": "octocat", "repository_selection": "selected",
            "html_url": "https://github.com/settings/installations/1",
        }]},
    }

    shell._after_machine_github_check(report)

    prompt = shell._history[-1].prompt
    assert prompt.key == "project.mode"
    assert "github.connected" not in [view.prompt.key for view in shell._history]
    detail = setup_agent_response.question_fields(prompt)["detail"]
    assert "Success! Yoke GitHub App connected for octocat." in detail
    assert any('We recommend "All repositories"' in line for line in detail)
    assert any("https://github.com/settings/installations/1" in line for line in detail)
    assert "Review repository access with `yoke github status`." in detail
    assert len(prompt.choices) > 1
    assert shell._carried_detail_lines == []


@pytest.mark.parametrize("present", ["_goto", "_replace_current"])
def test_carryover_accumulates_until_the_next_answerable_screen(shell, present):
    shell._carry_detail_lines(["Connection ready."])
    shell._goto(_View(SetupPrompt(key="checking", step="project", title="Checking.")))
    shell._carry_detail_lines(["Folder already exists."])
    custom = Static("Custom body", markup=False)
    view = _View(
        SetupPrompt(key="decision", step="project", title="Choose.",
                    detail_lines=("Question detail.",),
                    choices=(SelectionRow("retry", "Retry", "try again"),)),
        builder=lambda: [custom],
    )

    getattr(shell, present)(view)

    assert view.prompt.detail_lines == ("Connection ready.", "Folder already exists.", "Question detail.")
    assert [widget.content for widget in view.builder()] == ["Connection ready.", "Folder already exists.", "Custom body"]
    assert view.prompt.choices[0].value == "retry"
    assert shell._carried_detail_lines == []
    shell._goto(_View(SetupPrompt(key="later", step="project", title="Later.",
                                 choices=(SelectionRow("finish", "Finish", "done"),))))
    assert shell._history[-1].prompt.detail_lines == ()
