"""CLI contract: free-text yoke commands accept --stdin / --content-file."""

from __future__ import annotations

from io import StringIO

import pytest

from yoke_cli.commands.adapters import dash_file, items_create, qa, qa_crud, task
from yoke_cli.commands.adapters import feedback as field_note


def _capture(monkeypatch, module):
    captured = {}

    def _dispatch(**kwargs):
        captured.update(kwargs)
        return 0

    if module in (items_create, dash_file, task):
        monkeypatch.setattr(items_create, "dispatch_create", _dispatch)
    else:
        monkeypatch.setattr(module, "dispatch_and_emit", _dispatch)
    return captured


def test_dash_filing_reads_spec_from_stdin(monkeypatch):
    captured = _capture(monkeypatch, dash_file)
    monkeypatch.setattr(
        "yoke_cli.commands.text_file.sys.stdin",
        StringIO("Fix the `yoke items get` copy.\n"),
    )

    assert (
        dash_file.dash_file(
            [
                "--title",
                "Tighten footer",
                "--stdin",
                "--execution-instructions-considered",
            ]
        )
        == 0
    )

    assert captured["payload"]["title"] == "Tighten footer"
    assert captured["payload"]["spec"] == "Fix the `yoke items get` copy.\n"


def test_dash_filing_reads_spec_from_spec_file(monkeypatch, tmp_path):
    captured = _capture(monkeypatch, dash_file)
    path = tmp_path / "instruction.txt"
    path.write_text("Use $(date) literally.\n", encoding="utf-8")

    assert (
        dash_file.dash_file(
            [
                "--title",
                "Tighten footer",
                "--spec-file",
                str(path),
                "--execution-instructions-considered",
            ]
        )
        == 0
    )

    assert captured["payload"]["spec"] == "Use $(date) literally.\n"


def test_task_filing_reads_spec_from_stdin(monkeypatch):
    captured = _capture(monkeypatch, task)
    monkeypatch.setattr(
        "yoke_cli.commands.text_file.sys.stdin",
        StringIO("Refresh the local inventory file.\n"),
    )

    assert (
        task.task_file(
            [
                "--title",
                "Refresh inventory",
                "--stdin",
                "--execution-instructions-considered",
            ]
        )
        == 0
    )

    assert captured["payload"]["spec"] == ("Refresh the local inventory file.\n")


@pytest.mark.parametrize("adapter", [dash_file, task])
@pytest.mark.parametrize("source", ["stdin", "file"])
@pytest.mark.parametrize("blank", ["", " \n"])
def test_direct_work_refuses_blank_spec_before_dispatch(
    monkeypatch,
    tmp_path,
    capsys,
    adapter,
    source,
    blank,
):
    dispatched = []
    monkeypatch.setattr(
        items_create, "dispatch_create", lambda **kw: dispatched.append(kw)
    )
    args = ["--title", "Work title", "--execution-instructions-considered"]
    if source == "stdin":
        monkeypatch.setattr("yoke_cli.commands.text_file.sys.stdin", StringIO(blank))
        args.append("--stdin")
    elif source == "file":
        path = tmp_path / "empty.txt"
        path.write_text(blank, encoding="utf-8")
        args.extend(["--spec-file", str(path)])

    command = adapter.dash_file if adapter is dash_file else adapter.task_file
    assert command(args) == 2
    assert not dispatched
    error = capsys.readouterr().err
    assert "--spec-file" in error and "--stdin" in error
    assert "SPEC_REQUIRED" in error or "is required" in error


def test_items_create_reads_spec_from_stdin(monkeypatch):
    captured = _capture(monkeypatch, items_create)
    monkeypatch.setattr(
        "yoke_cli.commands.text_file.sys.stdin",
        StringIO("Title with `ticks`\n"),
    )

    assert (
        items_create.items_create(
            [
                "--title",
                "Stored title",
                "--workflow",
                "issue",
                "--stdin",
                "--execution-instructions-considered",
                "--dry-run",
            ]
        )
        == 0
    )

    assert captured["payload"]["spec"] == "Title with `ticks`\n"


def test_qa_requirement_add_reads_specs_from_stdin(monkeypatch):
    captured = _capture(monkeypatch, qa_crud)
    monkeypatch.setattr(
        "yoke_cli.commands.text_file.sys.stdin",
        StringIO("Open the login route.\n"),
    )

    assert (
        qa_crud.qa_requirement_add(
            [
                "--item",
                "YOK-1",
                "--method-id",
                "browser-inspection",
                "--qa-phase",
                "verification",
                "--workflow-transition",
                "reviewed-implementation",
                "--stdin",
            ]
        )
        == 0
    )

    assert captured["payload"]["instructions"] == "Open the login route.\n"


def test_qa_requirement_update_reads_value_from_stdin(monkeypatch):
    captured = _capture(monkeypatch, qa)
    monkeypatch.setattr(
        "yoke_cli.commands.text_file.sys.stdin",
        StringIO("new policy\n"),
    )

    assert (
        qa.qa_requirement_update(
            [
                "--requirement-id",
                "12",
                "--field",
                "success_policy",
                "--stdin",
            ]
        )
        == 0
    )

    assert captured["payload"]["value"] == "new policy\n"


def test_field_note_append_reads_evidence_from_stdin(monkeypatch):
    captured = _capture(monkeypatch, field_note)
    monkeypatch.setattr(
        "yoke_cli.commands.text_file.sys.stdin",
        StringIO("command `yoke dash` substituted\n"),
    )

    assert (
        field_note.feedback_append(
            [
                "--to", "universe", "--category",
                "observation",
                "--stdin",
            ]
        )
        == 0
    )

    assert captured["payload"]["evidence"] == ("command `yoke dash` substituted\n")
