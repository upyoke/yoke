"""Managed Git surfaces and uninstall round trips for project install."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_cli.project_install import checkout_gate, clone_excludes
from yoke_cli.project_install import runner as project_install
from yoke_cli.project_install.runner import apply_bundle
from yoke_core.domain.project_install_test_helpers import DEFAULT_FILES, make_bundle


MANIFEST_REL = ".yoke/install-manifest.json"


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "yoke_cli.project_install.uninstall_commit.dispatch",
        lambda *_args, **_kwargs: {"value": "trunk"},
    )
    root = tmp_path / "repo"
    root.mkdir()
    return root


def _manifest(repo) -> dict:
    return json.loads((repo / MANIFEST_REL).read_text(encoding="utf-8"))


def _tree_bytes(root: Path) -> dict[str, bytes | str]:
    snapshot = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        snapshot[rel] = (
            f"symlink:{path.readlink()}"
            if path.is_symlink()
            else path.read_bytes()
            if path.is_file()
            else "directory"
        )
    return snapshot


def _git_init(root) -> None:
    import subprocess

    subprocess.run(["git", "init", "-q", "-b", "trunk"], cwd=root, check=True)
    for key, value in (("user.name", "Yoke Test"), ("user.email", "tests@example.invalid")):
        subprocess.run(["git", "config", "--local", key, value], cwd=root, check=True)


def test_manifest_and_report_record_copy_mode(repo) -> None:
    report = apply_bundle(repo, make_bundle(), source="test")

    assert report["mode"] == "copy"
    assert _manifest(repo)["mode"] == "copy"


def test_fresh_install_and_uninstall_leave_git_hooks_alone(repo) -> None:
    _git_init(repo)
    hooks = repo / ".git/hooks"
    before = {hook.name: hook.read_bytes() for hook in hooks.iterdir()}

    installed = apply_bundle(repo, make_bundle(), source="test")
    assert installed["git_hooks_removed"] == []
    assert {hook.name: hook.read_bytes() for hook in hooks.iterdir()} == before

    checkout_gate.commit_touched_paths(repo, installed)
    report = project_install.uninstall(repo)
    assert report["git_hooks_removed"] == []
    assert {hook.name: hook.read_bytes() for hook in hooks.iterdir()} == before


def test_clone_excludes_install_and_uninstall_preserve_foreign_rules(repo) -> None:
    _git_init(repo)
    root_ignore = repo / ".gitignore"
    root_ignore.write_text("dist/\n", encoding="utf-8")
    checkout_gate.run_git(repo, "add", ".gitignore")
    assert checkout_gate.run_git(repo, "commit", "-m", "seed").returncode == 0
    exclude = repo / ".git/info/exclude"
    exclude.write_bytes(b"# operator note\r\n/.worktrees/\r\n")

    report = apply_bundle(repo, make_bundle(), source="test")
    assert root_ignore.read_text(encoding="utf-8") == "dist/\n/.claude/skills/yoke\n"
    assert _manifest(repo)["clone_excludes"] == ["/.claude/settings.local.json"]
    checkout_gate.commit_touched_paths(repo, report)
    assert checkout_gate.porcelain(repo) == []

    report = project_install.uninstall(repo)

    assert root_ignore.read_text(encoding="utf-8") == "dist/\n"
    assert report["clone_excludes_removed"] == ["/.claude/settings.local.json"]
    assert exclude.read_bytes().startswith(b"# operator note\r\n/.worktrees/\r\n")
    assert b"/.claude/settings.local.json" not in exclude.read_bytes()


@pytest.mark.parametrize("repair", [False, True])
def test_legacy_root_ignore_line_survives(repo, repair) -> None:
    _git_init(repo)
    root_ignore = repo / ".gitignore"
    root_ignore.write_text(".worktrees/\n", encoding="utf-8")
    checkout_gate.run_git(repo, "add", ".gitignore")
    assert checkout_gate.run_git(repo, "commit", "-m", "seed").returncode == 0
    report = apply_bundle(repo, make_bundle(), source="test")
    checkout_gate.commit_touched_paths(repo, report)
    manifest = _manifest(repo)
    owned = manifest.pop("clone_excludes")
    clone_excludes.remove(repo, owned)
    manifest["worktrees_ignore_added"] = True
    manifest["worktrees_ignore_created_file"] = True
    (repo / MANIFEST_REL).write_text(json.dumps(manifest), encoding="utf-8")
    checkout_gate.run_git(repo, "add", "-f", MANIFEST_REL)
    commit = checkout_gate.run_git(repo, "commit", "-m", "record legacy install")
    assert commit.returncode == 0, commit.stderr

    if repair:
        report = apply_bundle(repo, make_bundle(), source="test")
        checkout_gate.commit_touched_paths(repo, report)
        assert "worktrees_ignore_added" not in _manifest(repo)
        assert ".worktrees/" in root_ignore.read_text(encoding="utf-8").splitlines()
    project_install.uninstall(repo)
    assert root_ignore.read_text(encoding="utf-8") == ".worktrees/\n"


def test_install_refresh_drop_uninstall_round_trip(repo) -> None:
    apply_bundle(repo, make_bundle(), source="test")
    kept = DEFAULT_FILES[:2]
    dropped = [e["path"] for e in DEFAULT_FILES[2:]]

    report = apply_bundle(
        repo, make_bundle(files=kept), operation="refresh", source="test"
    )

    for path in dropped:
        assert path in report["files_pruned"]
        assert not (repo / path).exists()
    assert set(_manifest(repo)["files"]) == {e["path"] for e in kept}

    project_install.uninstall(repo)

    assert not (repo / MANIFEST_REL).exists()
    for entry in kept:
        assert not (repo / entry["path"]).exists()
