"""Regression: readiness repo-root resolution tolerates a missing ``git``.

``_resolve_repo_root`` shells out to ``git rev-parse --show-toplevel``. In
a function-dispatch context with a sanitized PATH the ``git`` binary is
absent and ``subprocess.run`` raises ``FileNotFoundError``. The resolver
must degrade to a filesystem walk-up / cwd instead of letting the error
escape and crash the readiness handler (observed live as
``readiness.check.run raised FileNotFoundError: 'git'``).
"""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain import idea_readiness_check_repo_root as rr


def _raise_missing_git(*_args, **_kwargs):
    raise FileNotFoundError(2, "No such file or directory", "git")


def test_resolve_repo_root_tolerates_missing_git(monkeypatch):
    monkeypatch.setattr(rr.subprocess, "run", _raise_missing_git)
    result = rr._resolve_repo_root()
    assert isinstance(result, Path)


def test_resolve_repo_root_for_item_no_conn_tolerates_missing_git(monkeypatch):
    monkeypatch.setattr(rr.subprocess, "run", _raise_missing_git)
    # conn=None delegates straight to _resolve_repo_root — must not raise.
    result = rr._resolve_repo_root_for_item(None, 0)
    assert isinstance(result, Path)


def test_repo_root_without_git_returns_path_without_subprocess(monkeypatch):
    # The git-free fallback must never shell out to git.
    monkeypatch.setattr(rr.subprocess, "run", _raise_missing_git)
    result = rr._repo_root_without_git()
    assert isinstance(result, Path)


def test_resolve_repo_root_uses_git_toplevel_when_available(monkeypatch, tmp_path):
    class _Proc:
        returncode = 0
        stdout = f"{tmp_path}\n"

    monkeypatch.setattr(rr.subprocess, "run", lambda *a, **k: _Proc())
    assert rr._resolve_repo_root() == tmp_path


def test_resolve_repo_root_falls_back_to_cwd_when_not_in_repo(monkeypatch):
    class _Proc:
        returncode = 128  # git ran but this is not a work tree
        stdout = ""

    monkeypatch.setattr(rr.subprocess, "run", lambda *a, **k: _Proc())
    assert rr._resolve_repo_root() == Path.cwd()
