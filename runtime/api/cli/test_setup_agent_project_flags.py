"""Project preset changes retain intent without reusing path-specific answers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.api.cli.setup_agent_test_support import (
    AgentDriver,
    MACHINE_ONLY_ANSWERS,
    git_checkout,
    isolate_agent_setup,
)
from yoke_cli.config import setup_agent_answers

pytest.importorskip("textual")


def saved() -> dict:
    return json.loads(setup_agent_answers.store_path().read_text())


@pytest.mark.parametrize("set_on_resume", [False, True])
def test_checkout_and_prefix_flags_answer_project_questions(
    tmp_path, monkeypatch, capsys, set_on_resume
):
    fake = isolate_agent_setup(tmp_path, monkeypatch)
    checkout = git_checkout(tmp_path / "demo")
    drive = AgentDriver(capsys)
    flags = ("--checkout", str(checkout), "--public-item-prefix", "qnwb")
    code, lines = drive(flags=() if set_on_resume else flags)
    assert code == 0, lines

    for answer in ("project.mode=local-checkout", *MACHINE_ONLY_ANSWERS[1:]):
        code, lines = drive(answer)
        assert code == 0, lines
        if not set_on_resume:
            assert all(line.get("key") != "project.folder" for line in lines)
    if set_on_resume:
        assert lines[-1]["key"] == "project.folder"
        code, lines = drive(flags=flags)
        assert code == 0, lines
        assert lines[-1]["key"] == "project.mode"
        code, lines = drive("project.mode=local-checkout")

    assert code == 0, lines
    assert lines[-1]["key"] == "project.details"
    fields = {field["key"] for field in lines[-1]["fields"]}
    assert "project.details.name" in fields
    assert "project.details.prefix" not in fields
    assert drive() == (code, lines)

    for answer in (
        "project.details=continue", "hosting.provider=skip", "review.confirm=apply",
    ):
        code, lines = drive(answer)
        assert code == 0, lines
    assert lines[-1]["state"] == "done"
    assert fake.applied[0]["project_checkout"] == str(checkout)
    assert fake.applied[0]["project_public_item_prefix"] == "QNWB"


@pytest.mark.parametrize("old_mode,new_mode", [
    ("create-repo", "clone-remote"), ("clone-remote", "create-repo")
])
def test_project_switch_keeps_machine_answers_folder_and_prefix(
    tmp_path: Path, monkeypatch, capsys, old_mode, new_mode
):
    isolate_agent_setup(tmp_path, monkeypatch)
    drive = AgentDriver(capsys)
    drive.walk(MACHINE_ONLY_ANSWERS[:4])
    folder = str(tmp_path / "chosen")
    old_key = "project.clone_folder" if old_mode == "clone-remote" else "project.folder"
    store = setup_agent_answers.open_store()
    try:
        store.presets = {"project_mode": old_mode}
        store.stage({
            old_key: folder,
            "project.details.prefix": "TRIN",
            "project.details.slug": "old-name",
            "project.mode": old_mode,
            "project.clone_url": "https://github.com/acme/old.git",
            "project.publish": "publish",
        })
        store.flush(waiting_key="project.publish")
    finally:
        store.release()
    machine_answers = {k: v for k, v in saved()["answers"].items()
                       if not k.startswith("project.")}

    code, lines = drive(flags=("--project-mode", new_mode))

    assert code == 0, lines
    record = saved()
    assert {k: v for k, v in record["answers"].items()
            if not k.startswith("project.")} == machine_answers
    assert record["answers"]["project.folder"] == folder
    assert record["answers"]["project.clone_folder"] == folder
    assert record["answers"]["project.details.prefix"] == "TRIN"
    assert "project.clone_url" not in record["answers"]
    assert "project.publish" not in record["answers"]
    assert "old-name" not in record["answers"].values()
    assert record["presets"]["project_mode"] == new_mode
    assert drive()[0] == 0


@pytest.mark.parametrize("flag", [("--yes",), ("--env", "other"), ("--local",)])
def test_non_project_change_refuses_before_project_answers_change(
    tmp_path: Path, monkeypatch, capsys, flag
):
    isolate_agent_setup(tmp_path, monkeypatch)
    drive = AgentDriver(capsys)
    drive.walk(("project.mode=machine-only",))
    before = setup_agent_answers.store_path().read_bytes()

    code, lines = drive(flags=("--project-mode", "clone-remote", *flag))

    assert code == 2, lines
    assert lines[-1]["reason"] == "setup_agent_flags_changed"
    assert setup_agent_answers.store_path().read_bytes() == before


def test_project_flags_preserve_omitted_non_project_presets(tmp_path, monkeypatch):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
    store = setup_agent_answers.open_store()
    try:
        store.presets = {"env": "chosen", "project_mode": "create-repo"}
        store.stage({"connect.destination": "server"})
        store.flush(waiting_key="project.folder")
        assert store.apply_presets({"project_mode": "clone-remote"}) is None
        assert store.presets == {"env": "chosen", "project_mode": "clone-remote"}
        assert store.answers == {"connect.destination": "server"}
    finally:
        store.release()
