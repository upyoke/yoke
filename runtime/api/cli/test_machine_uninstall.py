"""Operator choices and safe refusals for full machine removal."""

from dataclasses import replace

import pytest

from yoke_cli.config import machine_uninstall as removal
from yoke_cli.config.machine_uninstall_inventory import Inventory, UninstallError
from yoke_cli.commands.tool_shaped import resolve_tool_shaped


@pytest.fixture
def inventory(tmp_path, monkeypatch):
    home = tmp_path / "machine"
    checkouts = (tmp_path / "one", tmp_path / "two")
    value = Inventory(home, home / "config.json", checkouts, (), False, None, ())
    monkeypatch.setattr(removal, "inspect", lambda: value)
    return value


def test_hosted_machine_asks_only_projects(inventory, monkeypatch):
    output, questions, removed = [], [], []
    monkeypatch.setattr(
        removal.steps,
        "remove",
        lambda inv, selected, emit: removed.append(selected) or 0,
    )

    def ask(question):
        questions.append(question)
        return "2"

    assert (
        removal.run(
            backup=None,
            projects=None,
            non_interactive=False,
            ask=ask,
            emit=output.append,
        )
        == 0
    )
    assert len(questions) == 1
    assert removed == [(inventory.projects[1],)]
    assert not any("WARNING" in line for line in output)


def test_data_warning_is_first_and_backup_precedes_project_question(
    inventory, monkeypatch
):
    value = replace(inventory, local_universe=True, local_env="local")
    monkeypatch.setattr(removal, "inspect", lambda: value)
    events, output = [], []
    monkeypatch.setattr(
        removal.steps, "back_up", lambda inv, emit: events.append("export")
    )
    monkeypatch.setattr(
        removal.steps,
        "remove",
        lambda inv, selected, emit: events.append("remove") or 0,
    )
    answers = iter(["backup", "none"])

    def ask(question):
        events.append(question)
        return next(answers)

    assert (
        removal.run(
            backup=None,
            projects=None,
            non_interactive=False,
            ask=ask,
            emit=output.append,
        )
        == 0
    )
    assert output[0].startswith("WARNING")
    assert events[1] == "export"
    assert "projects" in events[2]
    assert events[-1] == "remove"


def test_yes_never_chooses_data_loss(inventory, monkeypatch):
    monkeypatch.setattr(
        removal, "inspect", lambda: replace(inventory, local_universe=True)
    )
    monkeypatch.setattr(
        removal.steps, "remove", lambda *args: pytest.fail("must not uninstall")
    )
    with pytest.raises(UninstallError, match="uninstall_backup_choice_required"):
        removal.run(
            backup=None, projects="all", non_interactive=True, emit=lambda line: None
        )


@pytest.mark.parametrize("value", ["unknown", "", "0", "3"])
def test_invalid_selection_refuses_before_export(inventory, monkeypatch, value):
    monkeypatch.setattr(
        removal, "inspect", lambda: replace(inventory, local_universe=True)
    )
    monkeypatch.setattr(
        removal.steps,
        "back_up",
        lambda *args: pytest.fail("no export before validation"),
    )
    with pytest.raises(UninstallError, match="uninstall_project_not_registered"):
        removal.run(
            backup=True, projects=value, non_interactive=True, emit=lambda line: None
        )


def test_unattended_requires_projects(inventory):
    with pytest.raises(UninstallError, match="uninstall_projects_choice_required"):
        removal.run(backup=None, projects=None, non_interactive=True)


def test_selection_paths_and_duplicates(inventory):
    assert removal.select_projects(f"{inventory.projects[1]},2", inventory) == (
        inventory.projects[1],
    )
    assert removal.select_projects("all", inventory) == inventory.projects
    assert removal.select_projects("none", inventory) == ()


def test_command_is_client_local_and_help_safe():
    adapter, args = resolve_tool_shaped(["uninstall", "--help"])
    with pytest.raises(SystemExit) as caught:
        adapter(args)
    assert caught.value.code == 0


def test_hosted_backup_flag_refuses(inventory):
    with pytest.raises(UninstallError, match="uninstall_backup_not_applicable"):
        removal.run(backup=True, projects="none", non_interactive=True)


def test_eof_cancels_without_a_traceback_or_removal(inventory, monkeypatch):
    def ask(prompt):
        raise EOFError

    monkeypatch.setattr(
        removal.steps, "remove", lambda *args: pytest.fail("must not uninstall")
    )
    with pytest.raises(UninstallError, match="uninstall_cancelled"):
        removal.run(backup=None, projects=None, non_interactive=False, ask=ask)
