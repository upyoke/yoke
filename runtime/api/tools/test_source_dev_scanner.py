"""Registered scanners resolve the current Yoke checkout with no session."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from yoke_core.tools import source_dev_run, source_dev_scanner

REPO = Path(__file__).resolve().parents[3]
BUILD = "docs/teaching/tools/build.py"


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    """A minimal Yoke source checkout with one commit and the build scanner."""
    root = tmp_path / "yoke"
    (root / "runtime/harness").mkdir(parents=True)
    (root / "runtime/harness/README.md").write_text("")
    (root / "pyproject.toml").write_text('[project]\nname = "yoke"\n')
    (root / BUILD).parent.mkdir(parents=True)
    (root / BUILD).write_text("")
    _git("init", "-q", cwd=root)
    _git("add", ".", cwd=root)
    _git(
        "-c",
        "user.email=t@example.com",
        "-c",
        "user.name=t",
        "commit",
        "-q",
        "-m",
        "init",
        cwd=root,
    )
    return root.resolve()


def test_main_subdirectory_and_worktree_resolve_alike(checkout: Path, tmp_path: Path):
    worktree = tmp_path / "lane"
    _git("worktree", "add", "-q", str(worktree), cwd=checkout)
    cases = {
        checkout: checkout,
        checkout / "docs/teaching/tools": checkout,
        worktree.resolve(): worktree.resolve(),
        worktree / "runtime/harness": worktree.resolve(),
    }
    for cwd, expected in cases.items():
        assert source_dev_scanner.checkout_root(cwd) == (expected, None)
        assert source_dev_scanner.scanner_root(["python3", BUILD], cwd) == (
            expected,
            None,
        )


def test_outside_a_yoke_checkout_refuses_with_recovery(tmp_path: Path):
    plain = tmp_path / "plain"
    plain.mkdir()
    _git("init", "-q", cwd=plain)
    for cwd in (tmp_path, plain):
        root, error = source_dev_scanner.checkout_root(cwd)
        assert root is None
        assert error.startswith("not_yoke_source_checkout: ")
        assert "cd into a Yoke source checkout" in error
    assert source_dev_scanner.scanner_root(["python3", BUILD], plain) == (None, error)


def test_other_commands_are_not_scanners(checkout: Path):
    for command in (
        ["python3", "-c", "pass"],
        ["python3", "docs/other.py"],
        ["yoke", BUILD],
        ["python3", "../" + BUILD],
    ):
        assert source_dev_scanner.scanner_root(command, checkout) is None


def test_outside_refusal_reaches_dev_run_before_any_session_lookup(
    monkeypatch, tmp_path, capsys
):
    def _no_session(*_args):
        raise AssertionError("scanner path must not look up a session")

    monkeypatch.setattr(source_dev_run, "_claimed_root", _no_session)
    monkeypatch.chdir(tmp_path)
    assert source_dev_run.run(["python3", BUILD]) == 1
    assert "not_yoke_source_checkout" in capsys.readouterr().err


@pytest.mark.parametrize("args", [[], ["--check"]])
def test_teaching_build_runs_without_a_session_and_keeps_git_status(monkeypatch, args):
    from yoke_core.domain.source_python_environment import SourcePythonEnvironment

    def _no_session(*_args):
        raise AssertionError("scanner path must not look up a session")

    monkeypatch.setattr(source_dev_run, "_claimed_root", _no_session)
    monkeypatch.setattr(source_dev_run, "_record_main_checkout_fallback", _no_session)
    monkeypatch.setattr(
        source_dev_run.source_python_environment,
        "resolve",
        lambda root, env: SourcePythonEnvironment(sys.executable, dict(env), {}),
    )
    monkeypatch.chdir(REPO / "docs/teaching")
    before = subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO)

    assert source_dev_run.run(["python3", BUILD, *args]) == 0

    assert subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO) == before
    if not args:
        views = REPO / "docs/teaching/views"
        assert [path.name for path in views.iterdir()] == ["yokepedia.html"]
        assert not (REPO / "docs/teaching/live").exists()
