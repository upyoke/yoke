"""Hook plans and installation agree for fresh clones and non-main checkouts."""

from pathlib import Path

import pytest

from yoke_cli.project_install import git_hooks as mod


def test_missing_hooks_directory_is_planned_and_created(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    specs = mod.managed_git_hook_specs()
    preview = mod.preview_git_hooks(tmp_path, specs)
    assert preview.installed == len(specs)
    assert not (tmp_path / ".git" / "hooks").exists()

    result = mod.BootstrapResult()
    mod.install_git_hooks(tmp_path, result, specs)
    assert result.installed == len(specs)
    for spec in specs:
        path = tmp_path / ".git" / "hooks" / spec["name"]
        assert path.read_text() == spec["content"]
        assert path.stat().st_mode & 0o111
    assert mod.preview_git_hooks(tmp_path, specs).installed == 0


@pytest.mark.parametrize("git_file", [False, True])
def test_absent_git_or_linked_worktree_keeps_skip_note(tmp_path: Path, git_file):
    if git_file:
        (tmp_path / ".git").write_text("gitdir: /some/main/.git/worktrees/lane\n")
    specs = mod.managed_git_hook_specs()
    preview = mod.preview_git_hooks(tmp_path, specs)
    result = mod.BootstrapResult()
    mod.install_git_hooks(tmp_path, result, specs)
    for report in (preview, result):
        assert report.installed == 0
        assert len(report.actions) == len(specs)
        assert all("Skipped: .git/hooks/" in note for note in report.actions)
        assert all("not a git repo, or a linked worktree" in note for note in report.actions)
    assert not (tmp_path / ".git" / "hooks").exists()
