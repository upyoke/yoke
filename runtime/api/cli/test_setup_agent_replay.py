"""Agent setup replays to the same question after every answer, in every project mode.

Each call rebuilds the run from its stored answers and run facts. A step that
changed the world — a clone, Apply's folder, checkout registration and local
universe — must not send the replay down a different branch.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from runtime.api.cli.setup_agent_test_support import (
    AgentDriver,
    fake_clone,
    git_checkout,
    isolate_agent_setup,
)
from yoke_cli.config import (
    existing_project_lookup,
    local_universe_setup,
    machine_config,
    onboard_wizard,
    project_onboard_clone,
    yoke_dev_detect,
)
from yoke_cli.config.onboard_wizard_flow_clone_source import (
    CloneRemoteCheck,
    CloneSourceFlow,
)
from yoke_cli.config.onboard_wizard_project_identity_flow import ProjectIdentityFlow

pytest.importorskip("textual")

REMOTE = "https://github.com/acme/demo.git"
FIRST_ANSWERS = {
    "connect.destination": "local",
    "connect.local_universe": "fresh",
    "connect.admin_name": "Test Person",
    "github.machine": "skip",
    "project.publish": "keep-local",
    "project.checkout_layer": "keep",
    "hosting.provider": "skip",
}


@pytest.fixture
def agent(tmp_path: Path, monkeypatch, capsys):
    fake = isolate_agent_setup(tmp_path, monkeypatch)
    monkeypatch.setattr(
        project_onboard_clone, "clone_with_connected_access", fake_clone
    )
    monkeypatch.setattr(
        CloneSourceFlow,
        "_probe_clone_remote",
        lambda _self, _url: CloneRemoteCheck("main", False),
    )
    monkeypatch.setattr(yoke_dev_detect, "detect_yoke_checkouts", lambda: [])
    return AgentDriver(capsys), fake


def walk_to_review(
    drive: AgentDriver, answers: dict[str, str], *, stop: str = "review.confirm"
) -> list[str]:
    """Answer each question (named answer, else its first choice), replaying each time."""
    asked: list[str] = []
    line = drive.replayed()
    while line["key"] != stop:
        key = line["key"]
        assert key not in asked[-3:], (key, asked)
        asked.append(key)
        choices = [row["value"] for row in line.get("answers") or []]
        value = {**FIRST_ANSWERS, **answers}.get(key) or (choices and choices[0])
        assert value, f"no answer for {key}"
        line = drive.replayed(f"{key}={value}")
    return asked


@pytest.mark.parametrize(
    ("mode", "folder_key", "expected"),
    [
        ("machine-only", None, "project.mode"),
        ("local-checkout", "project.folder", "project.details"),
        ("create-repo", "project.folder", "project.details"),
        ("clone-remote", "project.clone_folder", "project.checkout_layer"),
        ("edit-yoke-source", "project.source_folder", "project.source_remote"),
    ],
)
def test_every_project_mode_replays_to_the_same_question(
    agent, tmp_path: Path, mode, folder_key, expected
):
    drive, fake = agent
    folder = tmp_path / "code" / "demo"
    if mode == "local-checkout":
        git_checkout(folder)
    answers = {
        "project.mode": mode,
        "project.clone_url": REMOTE,
        "project.source_choice": "clone",
        "project.source_remote": REMOTE,
    }
    if folder_key:
        answers[folder_key] = str(folder)

    asked = walk_to_review(drive, answers)

    assert expected in asked
    assert "project.clone_resume" not in asked
    code, lines = drive("review.confirm=apply")
    assert (code, lines[-1]["state"]) == (0, "done"), lines[-1]
    assert fake.applied[0]["project_mode"] == mode


def test_an_existing_project_cloned_in_the_project_step_takes_its_layer_answer(
    agent, tmp_path: Path, monkeypatch
):
    drive, _ = agent
    project = existing_project_lookup.ExistingProject(
        7, "demo", "Demo", "acme/demo", "main", "DEMO"
    )
    monkeypatch.setattr(
        ProjectIdentityFlow, "_yoke_token_for_project_lookup", lambda _self: "token"
    )
    monkeypatch.setattr(
        existing_project_lookup, "find_by_github_repo", lambda **_k: project
    )
    folder = tmp_path / "code" / "demo"
    answers = {
        "project.mode": "clone-remote",
        "project.clone_url": REMOTE,
        "project.existing_found": "connect",
        "project.clone_folder": str(folder),
    }

    asked = walk_to_review(drive, answers, stop="hosting.provider")

    assert asked[-1] == "project.checkout_layer"
    assert (folder / ".git").is_dir()


@pytest.mark.parametrize("remote", [None, REMOTE])
def test_change_answers_after_a_failed_apply_replays_to_review(
    agent, tmp_path: Path, monkeypatch, remote
):
    drive, fake = agent
    folder = tmp_path / "code" / "demo"
    applied = {"done": False}
    real_inspect = local_universe_setup.inspect_local_state

    def inspect(config_path=None):
        if applied["done"]:
            return {"state": local_universe_setup.LOCAL_UNIVERSE_VERIFY, "active": True}
        return real_inspect(config_path)

    def registered(*_a, **_k):
        if not applied["done"]:
            return []
        return [machine_config.ConfiguredProject(folder, 42, {})]

    def effects(_kwargs):
        # What a real Apply leaves behind before it fails.
        applied["done"] = True
        if folder.exists():
            return
        git_checkout(folder)
        if remote:  # Apply published the repository before it failed.
            subprocess.run(
                ["git", "-C", str(folder), "remote", "add", "origin", remote],
                check=True,
            )

    monkeypatch.setattr(local_universe_setup, "inspect_local_state", inspect)
    monkeypatch.setattr(machine_config, "configured_projects", registered)
    monkeypatch.setattr(
        machine_config,
        "project_id",
        lambda root, *_a: 42 if applied["done"] and Path(root) == folder else None,
    )
    fake.effects = effects
    answers = {"project.mode": "create-repo", "project.folder": str(folder)}
    walk_to_review(drive, answers)
    fake.fail_next = onboard_wizard.WizardApplyError(
        "the relay did not start", failed_step="install-session-relay"
    )

    code, lines = drive("review.confirm=apply")
    assert (code, lines[-1]["key"]) == (1, "review.apply_failed"), lines[-1]

    line = drive.replayed("review.apply_failed=back")

    assert line["key"] == "review.confirm", line
    code, lines = drive("review.confirm=apply")
    assert (code, lines[-1]["state"]) == (0, "done"), lines[-1]
    assert fake.applied[-1]["project_mode"] == "create-repo"
