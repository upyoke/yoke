"""Ownership and failure behavior for clone-local Git excludes."""

from __future__ import annotations

import subprocess

import pytest

from yoke_cli.project_install import clone_excludes, install_recovery
from yoke_contracts.project_contract.install_error import ProjectInstallError


@pytest.fixture
def checkout(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return tmp_path, tmp_path / ".git/info/exclude"


def test_appends_only_missing_entries_and_removes_only_owned_lines(checkout):
    root, exclude = checkout
    foreign = b"# project comment\r\n/.worktrees/\r\n/other/\r\n"
    exclude.write_bytes(foreign)
    assert clone_excludes.preview(root) == ["/.claude/settings.local.json"]
    added = clone_excludes.append(root, clone_excludes.ENTRIES)
    assert added == ["/.claude/settings.local.json"]
    assert clone_excludes.append(root, clone_excludes.ENTRIES) == []
    assert exclude.read_bytes() == foreign + b"/.claude/settings.local.json\r\n"
    assert clone_excludes.remove(root, added, check=True) == added
    assert clone_excludes.remove(root, added) == added
    assert clone_excludes.remove(root, added) == []
    assert exclude.read_bytes() == foreign


def test_install_retry_keeps_pre_manifest_ownership(checkout):
    root, _ = checkout
    plan = {"candidate": {}, "checkout": {}}
    first = install_recovery.begin(root, plan, {})
    assert first == {"added": list(clone_excludes.ENTRIES), "owned": list(clone_excludes.ENTRIES)}
    retry = install_recovery.begin(root, plan, {})
    assert retry == {"added": [], "owned": first["owned"]}


def test_unwritable_exclude_refuses_with_path_and_recovery(checkout, monkeypatch):
    root, exclude = checkout
    before = exclude.read_bytes()

    def deny_write(*_args):
        raise PermissionError("access denied")

    monkeypatch.setattr(clone_excludes, "atomic_replace_bytes", deny_write)
    with pytest.raises(ProjectInstallError, match="clone_exclude_unwritable") as err:
        clone_excludes.append(root, clone_excludes.ENTRIES)
    assert str(exclude) in str(err.value)
    assert "access denied" in str(err.value)
    assert "rerun yoke project install" in str(err.value)
    assert exclude.read_bytes() == before


def test_unreadable_exclude_refuses_without_replacing_directory(checkout):
    root, exclude = checkout
    exclude.unlink()
    exclude.mkdir()
    with pytest.raises(ProjectInstallError, match="clone_exclude_unwritable"):
        clone_excludes.preview(root)
    assert exclude.is_dir()
