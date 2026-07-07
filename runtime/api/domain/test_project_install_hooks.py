"""Tests for hook merge/de-merge and ``yoke project uninstall``."""

from __future__ import annotations

import json

import pytest

from yoke_core.domain import project_install
from yoke_core.domain.project_install import ProjectInstallError, apply_bundle
from yoke_core.domain.project_install_test_helpers import (
    CLAUDE_PRE_CMD,
    DEFAULT_CONTRACT_FILES,
    DEFAULT_FILES,
    entry,
    make_bundle,
)

SETTINGS_REL = ".claude/settings.json"
FOREIGN = {
    "matcher": "Bash",
    "hooks": [{"type": "command", "command": "echo operator-owned"}],
}


@pytest.fixture()
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    return root


def _settings(repo, rel=SETTINGS_REL) -> dict:
    return json.loads((repo / rel).read_text(encoding="utf-8"))


def _write_settings(repo, payload, rel=SETTINGS_REL) -> None:
    (repo / rel).parent.mkdir(parents=True, exist_ok=True)
    (repo / rel).write_text(json.dumps(payload, indent=2) + "\n", "utf-8")


def test_merge_creates_settings_file_with_exact_subtree(repo) -> None:
    bundle = make_bundle()

    apply_bundle(repo, bundle, source="test")

    payload = _settings(repo)
    assert payload == {"hooks": bundle["hooks"]["claude_settings_hooks"]}
    raw = (repo / SETTINGS_REL).read_text("utf-8")
    assert raw.endswith("\n") and '  "hooks"' in raw  # pretty-printed


def test_merge_preserves_foreign_entries_and_appends_missing(repo) -> None:
    yoke_bash = entry(CLAUDE_PRE_CMD, "Bash")
    _write_settings(
        repo, {"hooks": {"PreToolUse": [FOREIGN, yoke_bash]}, "other": 1}
    )

    report = apply_bundle(repo, make_bundle(), source="test")

    payload = _settings(repo)
    pre = payload["hooks"]["PreToolUse"]
    assert pre[0] == FOREIGN, "foreign entries keep their position"
    assert pre[1] == yoke_bash, "existing Yoke entry is not duplicated"
    assert entry(CLAUDE_PRE_CMD, "Edit") in pre, "missing matcher appended"
    assert payload["other"] == 1
    assert payload["hooks"]["Stop"], "missing event key added"
    added = report["hooks_added"][SETTINGS_REL]
    assert {(r["event"], r["matcher"]) for r in added} == {
        ("PreToolUse", "Edit"), ("Stop", None),
    }
    assert SETTINGS_REL not in report["created_settings_files"]


def test_merge_distinguishes_matchers_sharing_one_command(repo) -> None:
    # Every Yoke PreToolUse matcher shares one command; identity must be
    # (matcher, command), not the command string alone.
    _write_settings(
        repo, {"hooks": {"PreToolUse": [entry(CLAUDE_PRE_CMD, "Bash")]}}
    )

    apply_bundle(repo, make_bundle(), source="test")

    matchers = [
        e.get("matcher") for e in _settings(repo)["hooks"]["PreToolUse"]
    ]
    assert matchers == ["Bash", "Edit"]


def test_invalid_settings_json_fails_loudly(repo) -> None:
    (repo / ".claude").mkdir(parents=True)
    (repo / SETTINGS_REL).write_text("{not json", encoding="utf-8")

    with pytest.raises(ProjectInstallError):
        apply_bundle(repo, make_bundle(), source="test")


def test_uninstall_removes_yoke_files_hooks_and_manifest(repo) -> None:
    apply_bundle(repo, make_bundle(), source="test")
    modified = DEFAULT_FILES[0]["path"]
    (repo / modified).write_text("operator edits\n", encoding="utf-8")

    report = project_install.uninstall(repo)

    assert sorted(report["files_removed"]) == sorted(
        e["path"] for e in DEFAULT_FILES[1:]
    )
    assert report["files_skipped_modified"] == [modified]
    assert (repo / modified).read_text("utf-8") == "operator edits\n"
    assert report["manifest_removed"] is True
    assert not (repo / ".yoke").exists(), "empty .yoke dir removed"
    # Created-by-install settings files become {"hooks": {}}-empty -> deleted.
    assert sorted(report["settings_files_deleted"]) == [
        ".claude/settings.json", ".codex/hooks.json",
    ]
    assert not (repo / SETTINGS_REL).exists()
    assert not (repo / ".codex/hooks.json").exists()


def test_uninstall_preserves_preexisting_settings_and_foreign_entries(
    repo,
) -> None:
    _write_settings(repo, {"hooks": {"PreToolUse": [FOREIGN]}})

    apply_bundle(repo, make_bundle(), source="test")
    report = project_install.uninstall(repo)

    assert ".claude/settings.json" not in report["settings_files_deleted"]
    payload = _settings(repo)
    assert payload["hooks"]["PreToolUse"] == [FOREIGN]
    assert "Stop" not in payload["hooks"], "event that held only ours removed"
    removed = report["hooks_removed"][SETTINGS_REL]
    assert {(r["event"], r["matcher"]) for r in removed} == {
        ("PreToolUse", "Bash"), ("PreToolUse", "Edit"), ("Stop", None),
    }


def test_uninstall_keeps_created_settings_file_grown_foreign_entries(
    repo,
) -> None:
    apply_bundle(repo, make_bundle(), source="test")
    payload = _settings(repo)
    payload["hooks"]["PreToolUse"].append(FOREIGN)
    _write_settings(repo, payload)

    report = project_install.uninstall(repo)

    assert ".claude/settings.json" not in report["settings_files_deleted"]
    assert _settings(repo)["hooks"]["PreToolUse"] == [FOREIGN]


def test_uninstall_removes_unchanged_contract_files(repo) -> None:
    apply_bundle(repo, make_bundle(), source="test")

    report = project_install.uninstall(repo)

    assert sorted(report["contract_files_removed"]) == sorted(
        e["path"] for e in DEFAULT_CONTRACT_FILES
    )
    assert report["contract_files_preserved_modified"] == []
    assert report["contract_files_already_absent"] == []
    assert not (repo / ".yoke").exists(), "emptied contract dirs removed"


def test_uninstall_preserves_modified_and_preexisting_contract_files(
    repo,
) -> None:
    preexisting = ".yoke/lint-config"
    (repo / ".yoke").mkdir()
    (repo / preexisting).write_text("project-authored policy\n", "utf-8")
    apply_bundle(repo, make_bundle(), source="test")
    edited = DEFAULT_CONTRACT_FILES[1]["path"]
    (repo / edited).write_text("project tuning\n", encoding="utf-8")
    deleted = DEFAULT_CONTRACT_FILES[2]["path"]
    (repo / deleted).unlink()

    report = project_install.uninstall(repo)

    assert report["contract_files_preserved_modified"] == [edited]
    assert report["contract_files_already_absent"] == [deleted]
    assert sorted(report["contract_files_removed"]) == sorted(
        e["path"] for e in DEFAULT_CONTRACT_FILES
        if e["path"] not in (preexisting, edited, deleted)
    ), "pre-existing files were never recorded, so never removed"
    assert (repo / preexisting).read_text("utf-8") == (
        "project-authored policy\n"
    )
    assert (repo / edited).read_text("utf-8") == "project tuning\n"
    assert any(edited in warning for warning in report["warnings"])
    assert (repo / ".yoke").exists(), "preserved files keep the dir"


def test_uninstall_without_manifest_is_a_typed_error(repo) -> None:
    with pytest.raises(ProjectInstallError) as exc_info:
        project_install.uninstall(repo)
    assert "install-manifest" in str(exc_info.value)
