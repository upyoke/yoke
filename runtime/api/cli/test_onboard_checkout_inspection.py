"""The pre-Apply checkout inspection: scan, removal, and the apply refusal."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from yoke_cli.config import project_installed_layer as layer
from yoke_cli.config import project_installed_layer_removal as removal
from yoke_cli.config import onboard_post_checkout_plan
from yoke_cli.config import project_onboard_installed_layer
from yoke_cli.config.project_clone_support import ClonePlan
from yoke_cli.config.project_onboard_support import ProjectOnboardError
from yoke_contracts.project_contract.installed_layer import (
    INSTALLED_LAYER_RECEIPT_REL,
)

from runtime.api.cli.onboard_checkout_inspection_fixtures import (
    clean_repo as _clean_repo,
    git_repo as _git_repo,
    repo_with_layer as _repo_with_layer,
)


def test_clean_repository_scans_as_a_first_install(tmp_path: Path) -> None:
    scan = layer.scan(_clean_repo(tmp_path))

    assert scan.present is False
    assert scan.file_count == 0
    assert scan.as_dict()["groups"] == []


def test_missing_folder_scans_empty_rather_than_failing(tmp_path: Path) -> None:
    assert layer.scan(tmp_path / "nothing-here").present is False


def test_scan_reports_every_place_the_layer_sits(tmp_path: Path) -> None:
    scan = layer.scan(_repo_with_layer(tmp_path))

    groups = {group.rel: group for group in scan.groups}
    assert groups[".yoke"].file_count == 2
    assert groups[".agents/skills/yoke"].file_count == 1
    assert groups[".claude/rules"].file_count == 1
    # The shared agents directory contributes only the yoke- adapters.
    assert groups[".claude/agents"].file_count == 1
    assert groups["AGENTS.md"].kind == layer.KIND_MARKDOWN_BLOCK
    assert groups[".claude/settings.json"].file_count == 1
    assert scan.source_engine_release == "0.1.1"


def test_removal_takes_the_layer_and_leaves_the_project(tmp_path: Path) -> None:
    root = _repo_with_layer(tmp_path)

    report = removal.remove(root)

    assert not (root / ".yoke").exists()
    assert not (root / ".agents").exists()
    assert not (root / ".claude/skills").exists()
    assert not (root / ".claude/agents/yoke-engineer.md").exists()
    assert not (root / INSTALLED_LAYER_RECEIPT_REL).exists()
    assert (root / "README.md").is_file()
    assert (root / "src/app.py").is_file()
    assert (root / ".claude/agents/team-reviewer.md").is_file()
    assert "Our own text." in (root / "AGENTS.md").read_text(encoding="utf-8")
    assert "YOKE MANAGED BLOCK" not in (root / "AGENTS.md").read_text(encoding="utf-8")
    settings = json.loads((root / ".claude/settings.json").read_text(encoding="utf-8"))
    assert settings["model"] == "opus"
    assert [
        hook["command"]
        for entry in settings["hooks"]["PreToolUse"]
        for hook in entry["hooks"]
    ] == ["our-own-hook"]
    assert report["removed_path_count"] > 0
    assert layer.scan(root).present is False


def test_removal_commits_itself_in_a_git_checkout(tmp_path: Path) -> None:
    root = _repo_with_layer(tmp_path)
    _git_repo(root)

    report = removal.remove(root)

    assert report["committed"] is True
    subject = subprocess.run(
        ["git", "-C", str(root), "log", "-1", "--pretty=%s"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert subject == removal.REMOVAL_COMMIT_MESSAGE
    porcelain = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert porcelain == ""


def test_removal_of_a_clean_repository_changes_nothing(tmp_path: Path) -> None:
    root = _clean_repo(tmp_path)

    report = removal.remove(root)

    assert report["removed_paths"] == []
    assert report["committed"] is False


def test_apply_refuses_a_repository_nobody_inspected(tmp_path: Path) -> None:
    root = _repo_with_layer(tmp_path)

    with pytest.raises(ProjectOnboardError) as excinfo:
        project_onboard_installed_layer.apply_decision(root, "")

    message = str(excinfo.value)
    assert "already carries a Yoke operating layer" in message
    assert "--existing-yoke-layer remove" in message
    assert "--existing-yoke-layer keep" in message
    assert (root / ".yoke").is_dir()


def test_apply_keeps_the_layer_when_that_was_the_decision(tmp_path: Path) -> None:
    root = _repo_with_layer(tmp_path)

    assert (
        project_onboard_installed_layer.apply_decision(
            root, layer.LAYER_DECISION_KEEP
        )
        is None
    )
    assert (root / ".yoke").is_dir()


def test_apply_removes_the_layer_when_that_was_the_decision(tmp_path: Path) -> None:
    root = _repo_with_layer(tmp_path)
    steps: list[tuple[str, str, str]] = []

    report = project_onboard_installed_layer.apply_decision(
        root,
        layer.LAYER_DECISION_REMOVE,
        progress=lambda action, target, status: steps.append(
            (action, target, status)
        ),
    )

    assert report is not None
    assert not (root / ".yoke").exists()
    assert [status for _action, _target, status in steps] == ["running", "done"]
    assert steps[0][0] == project_onboard_installed_layer.REMOVE_LAYER_ACTION


def test_apply_needs_no_decision_for_a_clean_repository(tmp_path: Path) -> None:
    assert project_onboard_installed_layer.apply_decision(_clean_repo(tmp_path), "") is None


def test_plan_lists_the_removal_before_the_scaffold_install(tmp_path: Path) -> None:
    inputs = {
        "checkout": str(tmp_path / "buzz"),
        "clone": ClonePlan(
            existing_layer_decision=layer.LAYER_DECISION_REMOVE,
        ),
    }

    actions = [
        step["action"]
        for step in onboard_post_checkout_plan.post_checkout_steps(
            "clone-remote", inputs, reuse={},
        )
    ]

    assert project_onboard_installed_layer.REMOVE_LAYER_ACTION in actions
    assert actions.index(
        project_onboard_installed_layer.REMOVE_LAYER_ACTION
    ) < actions.index("project-install-scaffold")


def test_plan_omits_the_removal_when_the_layer_is_kept(tmp_path: Path) -> None:
    inputs = {
        "checkout": str(tmp_path / "buzz"),
        "clone": ClonePlan(existing_layer_decision=layer.LAYER_DECISION_KEEP),
    }

    actions = [
        step["action"]
        for step in onboard_post_checkout_plan.post_checkout_steps(
            "clone-remote", inputs, reuse={},
        )
    ]

    assert project_onboard_installed_layer.REMOVE_LAYER_ACTION not in actions
