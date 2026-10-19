"""Filing preserves independent title/spec sources for every selected workflow."""

from io import StringIO

import pytest

from yoke_cli.commands.adapters import items_create, task, dash_file


@pytest.fixture
def calls(monkeypatch):
    requests = []
    monkeypatch.setattr(
        items_create, "dispatch_create", lambda **kw: requests.append(kw) or 0
    )
    monkeypatch.setattr(items_create, "refuse_unscaffolded_create", lambda **kw: None)
    return requests


@pytest.mark.parametrize(
    "workflow", ["task", "dash", "issue", "epic", "blitz", "custom"]
)
@pytest.mark.parametrize("source", ["file", "stdin"])
def test_any_workflow_accepts_multiline_spec_and_title_file(
    calls,
    monkeypatch,
    tmp_path,
    workflow,
    source,
):
    title = tmp_path / "title.txt"
    title.write_text("File the outcome\n")
    spec = "Keep `ticks` and $(shell) literal.\n\nSecond paragraph.\n"
    args = ["--workflow", workflow, "--title-file", str(title), "--project", "acme"]
    if source == "file":
        path = tmp_path / "spec.txt"
        path.write_text(spec)
        args += ["--spec-file", str(path)]
    else:
        monkeypatch.setattr("yoke_cli.commands.text_file.sys.stdin", StringIO(spec))
        args += ["--stdin"]
    assert items_create.items_create(args) == 0
    assert calls[0]["payload"]["title"] == "File the outcome"
    assert calls[0]["payload"]["spec"] == spec
    assert calls[0]["payload"]["workflow"] == workflow


@pytest.mark.parametrize(
    "shortcut,workflow", [(task.task_file, "task"), (dash_file.dash_file, "dash")]
)
def test_shortcut_and_canonical_have_identical_payloads(
    calls, tmp_path, shortcut, workflow
):
    path = tmp_path / "spec.txt"
    path.write_text("Do the work.\n")
    common = [
        "--spec-file",
        str(path),
        "--project",
        "acme",
        "--execution-instructions-considered",
    ]
    assert shortcut(["--title", "Outcome", *common]) == 0
    assert (
        items_create.items_create(
            ["--title", "Outcome", "--workflow", workflow, *common]
        )
        == 0
    )
    assert calls[0] == calls[1]


@pytest.mark.parametrize(
    "flags",
    [
        ["--content-file", "old.txt"],
        ["--spec-file", "missing.txt"],
        ["--stdin", "--spec-file", "other.txt"],
    ],
)
def test_invalid_spec_source_refuses_before_dispatch(calls, flags, capsys):
    assert (
        items_create.items_create(["--title", "Outcome", "--workflow", "task", *flags])
        == 2
    )
    assert calls == []
    assert "--spec-file" in capsys.readouterr().err


def test_unreadable_title_names_title_file(calls, capsys):
    assert (
        items_create.items_create(
            [
                "--workflow",
                "task",
                "--title-file",
                "missing.txt",
                "--spec-file",
                "spec.txt",
            ]
        )
        == 2
    )
    assert calls == []
    assert "--title-file" in capsys.readouterr().err


def test_invalid_utf8_refuses_with_source_flag(calls, tmp_path, capsys):
    path = tmp_path / "spec.txt"
    path.write_bytes(b"\xff")
    assert (
        items_create.items_create(
            ["--title", "Outcome", "--workflow", "issue", "--spec-file", str(path)]
        )
        == 2
    )
    assert calls == []
    assert "ITEM_TEXT_SOURCE_INVALID" in capsys.readouterr().err


@pytest.mark.parametrize(
    "adapter,args,command",
    [
        (dash_file.dash_file, ["Outcome", "/tmp/spec.md"], "yoke dash"),
        (task.task_file, ["Outcome", "--stdin"], "yoke task"),
        (items_create.items_create, ["Outcome", "dash"], "yoke items create"),
    ],
)
def test_positional_text_refuses_with_flag_recipe(
    calls, capsys, adapter, args, command
):
    assert adapter(args) == 2
    assert calls == []
    err = capsys.readouterr().err
    assert "ITEM_TEXT_POSITIONAL_RETIRED" in err
    assert f"{command} --title TEXT" in err
    assert "--spec-file PATH (or --stdin)" in err


def test_spec_text_has_no_inline_flag(calls, capsys):
    assert dash_file.dash_file(["--title", "Outcome", "--spec", "text"]) == 2
    assert calls == []
