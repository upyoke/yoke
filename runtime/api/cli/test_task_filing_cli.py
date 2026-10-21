"""CLI contract for the laneless Task filing shortcut."""

from __future__ import annotations

from io import StringIO

import pytest

from yoke_cli.commands.adapters import task, items_create


@pytest.fixture(autouse=True)
def _spec_on_stdin(monkeypatch):
    monkeypatch.setattr("sys.stdin", StringIO("Refresh the local inventory file."))


def _capture(monkeypatch):
    captured = {}

    def _dispatch(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(items_create, "dispatch_create", _dispatch)
    return captured


def test_task_filing_dispatches_typed_cli_create(monkeypatch):
    captured = _capture(monkeypatch)

    assert (
        task.task_file(
            [
                "--title",
                "Refresh inventory",
                "--stdin",
                "--project",
                "yoke",
                "--priority",
                "low",
                "--execution-instructions-considered",
            ]
        )
        == 0
    )

    assert captured["payload"] == {
        "title": "Refresh inventory",
        "dry_run": False,
        "spec": "Refresh the local inventory file.",
        "workflow": "task",
        "entry_surface": "cli",
        "workflow_posture": {},
        "execution_instructions_considered": True,
        "project": "yoke",
        "priority": "low",
    }


def test_task_filing_never_attests_for_the_caller(monkeypatch):
    captured = _capture(monkeypatch)

    assert (
        task.task_file(
            [
                "--title",
                "Refresh inventory",
                "--stdin",
            ]
        )
        == 0
    )

    assert captured["payload"]["execution_instructions_considered"] is False


@pytest.mark.parametrize(
    ("flags", "reason", "alternative"),
    [
        (["--verification-plan", "smoke"], "TASK_VERIFICATION", "yoke dash"),
        (["--verification-method", "command"], "TASK_VERIFICATION", "yoke dash"),
        (["--path-claims"], "TASK_PATH_CLAIMS", "yoke dash"),
        (["--approval-on-done"], "TASK_APPROVAL", "yoke dash"),
        (["--deployment"], "TASK_DEPLOYMENT", "yoke dash"),
    ],
)
def test_task_filing_refuses_inapplicable_dash_postures(
    flags,
    reason,
    alternative,
    capsys,
):
    assert (
        task.task_file(
            [
                "--title",
                "Refresh inventory",
                "--stdin",
                *flags,
            ]
        )
        == 2
    )

    error = capsys.readouterr().err
    assert reason in error
    assert alternative in error


def test_task_help_is_the_deep_filing_home(capsys):
    with pytest.raises(SystemExit) as raised:
        task.task_file(["--help"])

    assert raised.value.code == 0
    help_text = capsys.readouterr().out
    assert "--approval-on-done" in help_text
