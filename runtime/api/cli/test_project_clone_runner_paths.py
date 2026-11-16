"""Clone targets are checked by path identity, with no inherited descriptors."""

from __future__ import annotations

import os
from pathlib import Path
import stat
import subprocess

import pytest

from yoke_cli.config import onboard_checkout_ownership
from yoke_cli.config import project_clone_runner as runner
from yoke_cli.config.project_git_process import run_network_git

pytestmark = pytest.mark.windows


class CloneError(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def _git_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        runner.project_git_prerequisite, "require_git_available", lambda: None
    )


def _clone(parent: Path, run, **kwargs):
    return runner.run_clone(
        parent=parent,
        name="widgets",
        clean_url="https://github.com/acme/widgets.git",
        config=(),
        token=None,
        runner=run,
        error_type=CloneError,
        **kwargs,
    )


def test_git_runs_in_the_created_target_and_marks_it_owned(tmp_path: Path) -> None:
    calls = []

    def run(command, **kwargs):
        calls.append(kwargs)
        (kwargs["cwd"] / ".git").mkdir()
        return subprocess.CompletedProcess(command, 0, "", "")

    _clone(tmp_path, run)

    assert calls[0]["cwd"] == tmp_path / "widgets"
    assert set(calls[0]) == {"cwd", "env"}
    assert onboard_checkout_ownership.capture(tmp_path / "widgets") is not None


def test_non_empty_target_is_refused_before_git(tmp_path: Path) -> None:
    (tmp_path / "widgets").mkdir()
    (tmp_path / "widgets" / "keep.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(CloneError, match="no longer an empty directory"):
        _clone(tmp_path, lambda *a, **k: pytest.fail("git must not run"))


def test_linked_target_is_refused_before_git(tmp_path: Path) -> None:
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "widgets").symlink_to(tmp_path / "elsewhere")

    with pytest.raises(CloneError, match="no longer an empty directory"):
        _clone(tmp_path, lambda *a, **k: pytest.fail("git must not run"))


def test_windows_reparse_point_is_not_a_plain_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reparse = 0x400
    monkeypatch.setattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", reparse, raising=False)

    class Junction:
        st_mode = stat.S_IFDIR | 0o700
        st_file_attributes = reparse

    class Folder:
        st_mode = stat.S_IFDIR | 0o700
        st_file_attributes = 0x10

    assert runner._is_plain_directory(Junction()) is False
    assert runner._is_plain_directory(Folder()) is True


def test_identity_change_between_attempts_is_refused(tmp_path: Path) -> None:
    claim = runner.CloneTargetClaim(identity=(1, 1))
    (tmp_path / "widgets").mkdir()

    with pytest.raises(CloneError, match="identity changed between attempts"):
        _clone(
            tmp_path,
            lambda *a, **k: pytest.fail("git must not run"),
            target_claim=claim,
        )


def test_real_local_clone_runs_through_the_bounded_runner(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "init", "-q", str(source)], check=True)
    (source / "README.md").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(source), "add", "."], check=True)
    subprocess.run(
        [
            "git", "-C", str(source), "-c", "user.name=t", "-c", "user.email=t@e",
            "commit", "-qm", "init",
        ],
        check=True,
    )
    parent = tmp_path / "parent"
    parent.mkdir()

    result = runner.run_clone(
        parent=parent,
        name="widgets",
        clean_url=source.as_uri(),
        config=(),
        token=None,
        runner=lambda command, **kwargs: run_network_git(
            command,
            **{**kwargs, "env": {**kwargs["env"], "GIT_ALLOW_PROTOCOL": "file"}},
        ),
        error_type=CloneError,
    )

    assert result.returncode == 0, result.stderr
    assert (parent / "widgets" / "README.md").read_text(encoding="utf-8").strip() == (
        "hello"
    )
    marker = onboard_checkout_ownership.capture(parent / "widgets")
    assert marker is not None
    assert marker["inode"] == os.lstat(parent / "widgets").st_ino
