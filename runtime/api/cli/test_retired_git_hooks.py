"""Legacy Git shim cleanup is confined to Git's common hooks directory."""

import subprocess
from pathlib import Path

import pytest

from yoke_cli.main import main as cli_main
from yoke_cli.project_install.retired_git_hooks import remove


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True,
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "--quiet", "-b", "main")
    git(tmp_path, "config", "user.name", "Yoke Test")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    return tmp_path


def _shim(name: str, command: str) -> str:
    return (
        f'#!/bin/sh\n# yoke-{name} hook installed by `yoke project install`\n'
        f'echo "Install advice varies between releases"\n{command}\n\n'
    )


def test_removes_shipped_shapes_from_linked_worktree(repo):
    git(repo, "commit", "--allow-empty", "-qm", "seed")
    lane = repo / "linked"
    git(repo, "worktree", "add", "-qb", "lane", str(lane))
    hooks = repo / ".git/hooks"
    shims = {
        "pre-commit": 'exec python3 -m yoke_core.domain.git_pre_commit "$@"',
        "pre-merge-commit": 'exec "$yoke_bin" git pre-commit "$@"',
        "post-commit": 'exec python3 -m yoke_core.domain.path_snapshots --ensure-head "$@"',
        "post-merge": 'exec yoke git post-merge "$@"',
        "post-rewrite": 'exec "$yoke_bin" git post-rewrite "$@"',
        "post-checkout": 'exec "$yoke_bin" git post-checkout "$@"',
    }
    for name, command in shims.items():
        text = _shim(name, command)
        if name == "post-checkout":
            text = text.replace("\n", "\r\n")
        (hooks / name).write_bytes(text.encode())
    foreign = hooks / "pre-push"
    foreign.write_bytes(b"#!/bin/sh\nexit 0\n")
    custom_dir = repo / "team-hooks"
    custom_dir.mkdir()
    custom = custom_dir / "pre-commit"
    custom.write_text(_shim("pre-commit", shims["pre-commit"]))
    git(repo, "config", "core.hooksPath", "team-hooks")

    assert remove(lane) == list(shims)
    assert not any((hooks / name).exists() for name in shims)
    assert foreign.read_bytes() == b"#!/bin/sh\nexit 0\n"
    assert custom.read_text() == _shim("pre-commit", shims["pre-commit"])
    assert git(repo, "config", "core.hooksPath") == "team-hooks"


def test_keeps_and_reports_edited_hook_and_preserves_foreign_hook(repo):
    hook = repo / ".git/hooks/pre-commit"
    edited = _shim("pre-commit", 'exec /team/gate "$@"')
    hook.write_text(edited, encoding="utf-8")
    foreign = repo / ".git/hooks/post-commit"
    foreign.write_text('#!/bin/sh\necho "yoke-post-commit"\n', encoding="utf-8")

    warnings = []
    assert remove(repo, warnings=warnings) == []
    assert hook.read_text() == edited
    assert foreign.is_file()
    assert len(warnings) == 1
    assert str(hook) in warnings[0]
    assert "remove it by hand" in warnings[0]


def test_missing_hooks_directory_is_left_absent(repo):
    hooks = repo / ".git/hooks"
    for entry in hooks.iterdir():
        entry.unlink()
    hooks.rmdir()

    assert remove(repo) == []
    assert not hooks.exists()


def test_git_hooks_and_snapshot_hook_flag_are_no_longer_commands(capsys):
    assert cli_main(["git", "pre-commit"]) == 2
    assert "unknown" in capsys.readouterr().err
    assert cli_main(["project", "snapshot", "sync", "--hook", "post-commit"]) == 2
    assert "--hook" in capsys.readouterr().err
