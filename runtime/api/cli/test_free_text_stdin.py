"""CLI contract: free-text yoke commands accept --stdin / --content-file."""

from __future__ import annotations

from io import StringIO

from yoke_cli.commands.adapters import dash_file, items_create, qa, qa_crud, task
from yoke_cli.commands.adapters import ouroboros_field_note as field_note


def _capture(monkeypatch, module):
    captured = {}

    def _dispatch(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(module, "dispatch_and_emit", _dispatch)
    return captured


def test_dash_filing_reads_instruction_from_stdin(monkeypatch):
    captured = _capture(monkeypatch, dash_file)
    monkeypatch.setattr(
        "yoke_cli.commands.text_file.sys.stdin",
        StringIO("Fix the `yoke items get` copy.\n"),
    )

    assert dash_file.dash_file([
        "Tighten footer",
        "--stdin",
        "--execution-instructions-considered",
    ]) == 0

    assert captured["payload"]["title"] == "Tighten footer"
    assert captured["payload"]["instruction"] == "Fix the `yoke items get` copy.\n"


def test_dash_filing_reads_instruction_from_content_file(monkeypatch, tmp_path):
    captured = _capture(monkeypatch, dash_file)
    path = tmp_path / "instruction.txt"
    path.write_text("Use $(date) literally.\n", encoding="utf-8")

    assert dash_file.dash_file([
        "Tighten footer",
        "--content-file",
        str(path),
        "--execution-instructions-considered",
    ]) == 0

    assert captured["payload"]["instruction"] == "Use $(date) literally.\n"


def test_task_filing_reads_instruction_from_stdin(monkeypatch):
    captured = _capture(monkeypatch, task)
    monkeypatch.setattr(
        "yoke_cli.commands.text_file.sys.stdin",
        StringIO("Refresh the local inventory file.\n"),
    )

    assert task.task_file([
        "Refresh inventory",
        "--stdin",
        "--execution-instructions-considered",
    ]) == 0

    assert captured["payload"]["instruction"] == (
        "Refresh the local inventory file.\n"
    )


def test_items_create_reads_title_from_stdin(monkeypatch):
    captured = _capture(monkeypatch, items_create)
    monkeypatch.setattr(items_create, "_refuse_unscaffolded_create", lambda **_: None)
    monkeypatch.setattr(
        "yoke_cli.commands.text_file.sys.stdin",
        StringIO("Title with `ticks`\n"),
    )

    assert items_create.items_create([
        "--stdin",
        "--execution-instructions-considered",
        "--dry-run",
    ]) == 0

    assert captured["payload"]["title"] == "Title with `ticks`\n"


def test_qa_requirement_add_reads_instructions_from_stdin(monkeypatch):
    captured = _capture(monkeypatch, qa_crud)
    monkeypatch.setattr(
        "yoke_cli.commands.text_file.sys.stdin",
        StringIO("Open the login route.\n"),
    )

    assert qa_crud.qa_requirement_add([
        "--item",
        "YOK-1",
        "--method-id",
        "browser-inspection",
        "--qa-phase",
        "verification",
        "--workflow-transition",
        "reviewed-implementation",
        "--stdin",
    ]) == 0

    assert captured["payload"]["instructions"] == "Open the login route.\n"


def test_qa_requirement_update_reads_value_from_stdin(monkeypatch):
    captured = _capture(monkeypatch, qa)
    monkeypatch.setattr(
        "yoke_cli.commands.text_file.sys.stdin",
        StringIO("new policy\n"),
    )

    assert qa.qa_requirement_update([
        "--requirement-id",
        "12",
        "--field",
        "success_policy",
        "--stdin",
    ]) == 0

    assert captured["payload"]["value"] == "new policy\n"


def test_field_note_append_reads_evidence_from_stdin(monkeypatch):
    captured = _capture(monkeypatch, field_note)
    monkeypatch.setattr(
        "yoke_cli.commands.text_file.sys.stdin",
        StringIO("command `yoke dash` substituted\n"),
    )

    assert field_note.ouroboros_field_note_append([
        "--kind",
        "observation",
        "--stdin",
    ]) == 0

    assert captured["payload"]["evidence"] == (
        "command `yoke dash` substituted\n"
    )
