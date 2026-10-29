"""CLI ``yoke items create`` files every workflow without a session-mode gate."""

from __future__ import annotations

from io import StringIO

import pytest

from yoke_cli.commands.adapters import dash_file, task, items_create


@pytest.fixture(autouse=True)
def _spec_on_stdin(monkeypatch):
    monkeypatch.setattr(
        "yoke_cli.commands.text_file.sys.stdin",
        StringIO("Agreed outcome: the item shows on the board."),
    )


@pytest.fixture
def captured(monkeypatch):
    payload: dict = {}
    monkeypatch.setenv("YOKE_SESSION_ID", "session-wait")
    monkeypatch.setattr(
        items_create, "dispatch_create", lambda **kw: payload.update(kw) or 0
    )
    return payload


@pytest.mark.parametrize("workflow", ["issue", "epic", "blitz"])
def test_session_files_a_non_dash_workflow(captured, workflow) -> None:
    assert (
        items_create.items_create(
            [
                "--title",
                "Planned outcome",
                "--workflow",
                workflow,
                "--stdin",
                "--entry-surface",
                "harness_skill",
                "--execution-instructions-considered",
            ]
        )
        == 0
    )
    assert captured["payload"]["workflow"] == workflow
    assert captured["payload"]["entry_surface"] == "harness_skill"


@pytest.mark.parametrize("workflow", ["dash", "task"])
@pytest.mark.parametrize("shortcut", [False, True])
def test_direct_skill_intake_preserves_surface_and_attestation(
    captured,
    workflow,
    shortcut,
):
    args = ["--title", "Direct outcome"]
    if not shortcut:
        args += ["--workflow", workflow]
    args += ["--stdin", "--entry-surface", "harness_skill"]
    command = (
        {"dash": dash_file.dash_file, "task": task.task_file}[workflow]
        if shortcut
        else items_create.items_create
    )
    assert command(args) == 0
    assert captured["payload"]["workflow"] == workflow
    assert captured["payload"]["entry_surface"] == "harness_skill"
    assert captured["payload"]["execution_instructions_considered"] is False
    assert captured["payload"]["spec"] == "Agreed outcome: the item shows on the board."
