"""Tests for the cwd/--rootdir cross-repo mismatch warning in
``yoke_core.tools._watch_pytest_rootdir`` (consumed by ``watch_pytest``).

Lives in its own module to keep ``test_watch_pytest.py`` under the
350-line authored-file cap. Covers:

- ``extract_rootdir`` parses both ``--rootdir <value>`` and
  ``--rootdir=<value>`` forms and returns ``None`` for malformed shapes.
- ``rootdir_mismatch_warning`` returns ``None`` when no ``--rootdir`` is
  set, when ``--rootdir`` resolves inside the cwd's git repo, or when
  one side is not inside a git repo. It returns a loud warning that
  names both repo paths when the rootdir and cwd live in different
  git repos — the invocation shape that produced the BoardDB.execute
  cascade observed during a conduct run.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from yoke_core.tools import _watch_pytest_rootdir


class TestExtractRootdir:
    """Cover the helper that parses ``--rootdir`` out of pytest pass-through."""

    def test_returns_none_when_absent(self) -> None:
        assert _watch_pytest_rootdir.extract_rootdir(["runtime/api/", "-q"]) is None

    def test_space_form(self) -> None:
        args = ["--rootdir", "/tmp/elsewhere", "runtime/api/"]
        assert _watch_pytest_rootdir.extract_rootdir(args) == "/tmp/elsewhere"

    def test_equals_form(self) -> None:
        args = ["--rootdir=/tmp/elsewhere", "runtime/api/"]
        assert _watch_pytest_rootdir.extract_rootdir(args) == "/tmp/elsewhere"

    def test_dangling_flag_returns_none(self) -> None:
        # ``--rootdir`` with no value is malformed; the helper does not
        # invent a value.
        assert _watch_pytest_rootdir.extract_rootdir(["--rootdir"]) is None


class TestRootdirMismatchWarning:
    """Cover the cwd/rootdir-repo mismatch detector."""

    def _init_repo(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q"], cwd=str(path), check=True)
        # Empty commit so rev-parse returns a stable toplevel.
        subprocess.run(
            [
                "git",
                "-c",
                "user.email=t@e",
                "-c",
                "user.name=t",
                "commit",
                "--allow-empty",
                "-qm",
                "init",
            ],
            cwd=str(path),
            check=True,
        )

    def test_no_rootdir_no_warning(self, tmp_path: Path) -> None:
        self._init_repo(tmp_path)
        warning = _watch_pytest_rootdir.rootdir_mismatch_warning(
            ["runtime/api/", "-q"], str(tmp_path)
        )
        assert warning is None

    def test_rootdir_same_repo_no_warning(self, tmp_path: Path) -> None:
        self._init_repo(tmp_path)
        nested = tmp_path / "nested"
        nested.mkdir()
        warning = _watch_pytest_rootdir.rootdir_mismatch_warning(
            ["--rootdir", str(nested), "runtime/api/"], str(tmp_path)
        )
        # ``nested`` lives inside the same repo as ``tmp_path``; both
        # ``git rev-parse --show-toplevel`` calls return ``tmp_path``.
        assert warning is None

    def test_cross_repo_warning_emitted(self, tmp_path: Path) -> None:
        repo_a = tmp_path / "repo_a"
        repo_b = tmp_path / "repo_b"
        self._init_repo(repo_a)
        self._init_repo(repo_b)
        warning = _watch_pytest_rootdir.rootdir_mismatch_warning(
            ["--rootdir", str(repo_b), "runtime/api/"], str(repo_a)
        )
        assert warning is not None
        assert "WARNING" in warning
        assert "cwd repo" in warning
        assert "--rootdir repo" in warning
        # Names both real paths so the operator can see which is which.
        assert os.path.realpath(str(repo_a)) in warning
        assert os.path.realpath(str(repo_b)) in warning

    def test_non_git_cwd_skips_warning(self, tmp_path: Path) -> None:
        # No ``git init`` here: rev-parse will fail; helper returns None
        # rather than emitting a confidence-light warning.
        repo_b = tmp_path / "repo_b"
        self._init_repo(repo_b)
        plain = tmp_path / "plain"
        plain.mkdir()
        warning = _watch_pytest_rootdir.rootdir_mismatch_warning(
            ["--rootdir", str(repo_b), "runtime/api/"], str(plain)
        )
        assert warning is None
