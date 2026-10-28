"""Project intent is collected before credentials and replayed after connection."""

from types import SimpleNamespace

import pytest

from runtime.api.cli.setup_agent_test_support import AgentDriver, isolate_agent_setup
from yoke_cli.config import onboard_project as modes
from yoke_cli.config.onboard_permission_review import SETUP_PERMISSION_DISCLOSURE
from yoke_cli.config.onboard_wizard import WizardDefaults
from yoke_cli.config.onboard_wizard_app import OnboardWizardApp
from yoke_cli.config.onboard_wizard_clone_git_copy import install_handoff_prompt
from yoke_cli.config.onboard_wizard_flow_project_git import ProjectGitFlow
from yoke_cli.config.onboard_wizard_flows import SETUP_FLOWS, init_setup_state


@pytest.mark.parametrize(
    "mode,next_key",
    [
        ("create-repo", "project.folder"),
        ("local-checkout", "project.folder"),
        ("clone-remote", "project.clone_url"),
        ("machine-only", "review.confirm"),
    ],
)
def test_agent_remembers_project_before_connection(
    tmp_path, monkeypatch, capsys, mode, next_key
):
    isolate_agent_setup(tmp_path, monkeypatch)
    monkeypatch.setattr(
        ProjectGitFlow,
        "_check_project_git",
        lambda self, mode: self._after_project_git_ready(mode),
    )
    drive = AgentDriver(capsys)
    code, lines = drive()
    assert code == 0
    assert lines[-1]["key"] == "project.mode"
    assert all(line in lines[-1]["detail"] for line in SETUP_PERMISSION_DISCLOSURE)
    assert [row["value"] for row in lines[-1]["answers"]] == [
        "create-repo",
        "local-checkout",
        "clone-remote",
        "edit-yoke-source",
        "machine-only",
    ]
    line = drive.replayed(f"project.mode={mode}")
    assert line["key"] == "connect.destination"
    assert not any(text in line["detail"] for text in SETUP_PERMISSION_DISCLOSURE)
    for answer in (
        "connect.destination=local",
        "connect.local_universe=fresh",
        "connect.admin_name=Test Person",
        "github.machine=skip",
    ):
        line = drive.replayed(answer)
    assert line["key"] == next_key


@pytest.mark.parametrize(
    "shell_type",
    [
        OnboardWizardApp,
        type(
            "FlowShell",
            SETUP_FLOWS,
            {
                "_goto": lambda self, view: self.views.append(view),
                "_start_connect": lambda self: self.events.append("connect"),
            },
        ),
    ],
)
def test_shared_install_routes_to_project_question(shell_type):
    shell = object.__new__(shell_type)
    init_setup_state(shell, defaults=WizardDefaults(), apply_report=lambda _: {})
    shell.views, shell.events = [], []
    shell._goto = shell.views.append
    shell._start_connect = lambda: shell.events.append("connect")
    shell._finish_install({}, "")
    assert shell.views[-1].prompt.key == "project.mode"
    shell.views[-1].on_select(modes.PROJECT_MODE_LOCAL_CHECKOUT)
    assert shell.events == ["connect"]
    assert shell._project_mode_preset
    assert shell.result.project_mode == modes.PROJECT_MODE_LOCAL_CHECKOUT


@pytest.mark.parametrize("preset,saved", [(True, False), (False, True)])
def test_presets_and_saved_checkouts_keep_connection_first(preset, saved):
    shell = SimpleNamespace(
        _checking=False,
        _checking_blocks_quit=False,
        result=SimpleNamespace(path_repair={}),
        _run_facts={},
        _history=[],
        _project_mode_preset=preset,
        _stored_project_checkouts=[object()] if saved else [],
        _start_connect=lambda: events.append("connect"),
    )
    events = []
    from yoke_cli.config.onboard_wizard_path import PathFlow

    PathFlow._finish_install(shell, {}, "")
    assert events == ["connect"]


def test_git_install_handoffs_keep_recovery_and_recheck(monkeypatch):
    from yoke_cli.config import project_git_prerequisite as git

    monkeypatch.setattr(git, "install_handoff_detail_lines", lambda _: [])
    clone = install_handoff_prompt(None)
    views = []
    shell = SimpleNamespace(_goto=views.append)
    ProjectGitFlow._goto_project_git_install_handoff(shell, "create-repo", None)
    for prompt in (clone, views[-1].prompt):
        assert "xcode-select --install" in prompt.message
        assert "retry" in [row.value for row in prompt.choices]


def test_wizard_first_question_and_deferred_existing_folder(monkeypatch, tmp_path):
    import asyncio
    from runtime.api.cli.onboard_wizard_test_helpers import stub_path_doctor
    from textual.widgets import Static

    stub_path_doctor(monkeypatch)
    app = OnboardWizardApp(
        defaults=WizardDefaults(
            config_path=str(tmp_path / "config.json"),
            api_url="https://api.test",
            token="actor-token",
        ),
        apply_report=lambda _: {},
    )
    monkeypatch.setattr(
        ProjectGitFlow,
        "_check_project_git",
        lambda self, mode: self._after_project_git_ready(mode),
    )

    async def scenario():
        async with app.run_test(size=(100, 45)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app._history[-1].prompt.key == "project.mode"
            assert app._history[-1].prompt.detail_lines == SETUP_PERMISSION_DISCLOSURE
            visible = "\n".join(str(widget.render()) for widget in app.query(Static))
            assert all(line in visible for line in SETUP_PERMISSION_DISCLOSURE)
            app.save_screenshot(str(tmp_path / "first-question.svg"))
            await pilot.press("down", "enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app._history[-1].prompt.key == "github.machine"
            await pilot.press("down", "enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app._history[-1].prompt.key == "project.folder"
            assert app.result.project_mode == modes.PROJECT_MODE_LOCAL_CHECKOUT

    asyncio.run(scenario())



def test_choose_another_restored_project_reasks_project_mode():
    shell_type = type("FlowShell", SETUP_FLOWS, {
        "_goto": lambda self, view: self.views.append(view),
    })
    shell = object.__new__(shell_type)
    init_setup_state(shell, defaults=WizardDefaults(), apply_report=lambda _: {})
    shell.views = []
    shell.result.project_mode = modes.PROJECT_MODE_CLONE_REMOTE
    shell._project_mode_preset = True
    shell._restored_projects = [{"id": 1, "slug": "demo"}]
    shell._goto_project_mode()
    assert shell.views[-1].prompt.key == "project.restored"
    shell.views[-1].on_select("other")
    assert shell.views[-1].prompt.key == "project.mode"
