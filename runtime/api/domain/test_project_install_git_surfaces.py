"""Managed Git surfaces and uninstall round trips for project install."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from yoke_core.domain import project_install
from yoke_core.domain.project_install import ProjectInstallError, apply_bundle
from yoke_core.domain.project_install_test_helpers import DEFAULT_FILES, make_bundle


MANIFEST_REL = ".yoke/install-manifest.json"


@pytest.fixture()
def repo(tmp_path):
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

    subprocess.run(["git", "init", "-q"], cwd=root, check=True)


def test_manifest_and_report_record_copy_mode(repo) -> None:
    report = apply_bundle(repo, make_bundle(), source="test")

    assert report["mode"] == "copy"
    assert _manifest(repo)["mode"] == "copy"


def test_copy_install_writes_git_hook_shims(repo) -> None:
    from yoke_core.domain import project_install_git_hooks as git_hooks

    _git_init(repo)

    report = apply_bundle(repo, make_bundle(), source="test")

    assert report["git_hooks_installed_or_updated"] == 2
    for name, marker in (
        ("pre-commit", git_hooks.PRE_COMMIT_MARKER),
        ("post-commit", git_hooks.POST_COMMIT_MARKER),
    ):
        hook = repo / ".git" / "hooks" / name
        assert hook.is_file(), f"{name} shim must be installed in copy mode"
        assert marker in hook.read_text(encoding="utf-8")

    rerun = apply_bundle(repo, make_bundle(), operation="refresh", source="test")
    assert rerun["git_hooks_installed_or_updated"] == 0
    assert rerun["warnings"] == []


def test_copy_install_skips_git_hooks_without_git_dir(repo) -> None:
    report = apply_bundle(repo, make_bundle(), source="test")

    assert report["git_hooks_installed_or_updated"] == 0
    assert [a for a in report["git_hook_actions"] if "Skipped" in a]
    assert report["warnings"] == []


def test_copy_uninstall_removes_yoke_hooks_preserves_foreign(repo) -> None:
    _git_init(repo)
    apply_bundle(repo, make_bundle(), source="test")
    foreign = repo / ".git" / "hooks" / "post-commit"
    foreign.write_text("#!/bin/sh\nexec /custom/notify\n", encoding="utf-8")

    report = project_install.uninstall(repo)

    assert report["git_hooks_removed"] == ["pre-commit"]
    assert not (repo / ".git" / "hooks" / "pre-commit").exists()
    assert foreign.read_text(encoding="utf-8") == ("#!/bin/sh\nexec /custom/notify\n")


def test_git_hook_marker_mention_is_never_treated_as_ownership(repo) -> None:
    _git_init(repo)
    ambiguous = repo / ".git" / "hooks" / "pre-commit"
    content = (
        "#!/bin/sh\n"
        "# docs mention yoke-pre-commit but this is operator-owned\n"
        "exec /custom/gate\n"
    )
    ambiguous.write_text(content, encoding="utf-8")

    report = apply_bundle(repo, make_bundle(), source="test")

    assert ambiguous.read_text(encoding="utf-8") == content
    assert any("not Yoke-managed" in warning for warning in report["warnings"])
    assert ".git/hooks/pre-commit" not in _manifest(repo)["git_hook_hashes"]

    uninstall_report = project_install.uninstall(repo)
    assert ambiguous.read_text(encoding="utf-8") == content
    assert uninstall_report["git_hooks_removed"] == ["post-commit"]


def test_worktrees_ignore_owned_line_round_trips_without_foreign_loss(repo) -> None:
    root_ignore = repo / ".gitignore"
    root_ignore.write_text("dist/\n# operator note\n", encoding="utf-8")

    apply_bundle(repo, make_bundle(), source="test")

    assert root_ignore.read_text(encoding="utf-8") == (
        "dist/\n# operator note\n.worktrees/\n"
    )
    manifest = _manifest(repo)
    assert manifest["worktrees_ignore_added"] is True
    assert manifest["worktrees_ignore_created_file"] is False

    report = project_install.uninstall(repo)

    assert root_ignore.read_text(encoding="utf-8") == "dist/\n# operator note\n"
    assert report["worktrees_ignore"] == {
        "removed": True,
        "deleted_file": False,
    }


def test_worktrees_ignore_created_file_is_removed_on_uninstall(repo) -> None:
    apply_bundle(repo, make_bundle(), source="test")
    assert _manifest(repo)["worktrees_ignore_created_file"] is True

    report = project_install.uninstall(repo)

    assert not (repo / ".gitignore").exists()
    assert report["worktrees_ignore"]["deleted_file"] is True


def test_git_hook_symlink_escape_fails_before_uninstall_mutation(
    repo,
    tmp_path,
) -> None:
    _git_init(repo)
    apply_bundle(repo, make_bundle(), source="test")
    hooks_dir = repo / ".git/hooks"
    shutil.rmtree(hooks_dir)
    outside_hooks = tmp_path / "outside-hooks"
    outside_hooks.mkdir()
    outside_hook = outside_hooks / "pre-commit"
    outside_hook.write_text("outside\n", encoding="utf-8")
    hooks_dir.symlink_to(outside_hooks, target_is_directory=True)
    before = _tree_bytes(repo)

    with pytest.raises(ProjectInstallError, match="resolves outside repo root"):
        project_install.uninstall(repo)

    assert _tree_bytes(repo) == before
    assert outside_hook.read_text(encoding="utf-8") == "outside\n"


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
