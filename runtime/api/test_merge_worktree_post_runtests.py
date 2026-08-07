"""Integrated-candidate verification through registered project commands."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from yoke_core.engines import merge_worktree_tests


def _ctx(tmp_path, *, project="example", item_id="42"):
    return SimpleNamespace(
        project=project,
        item_id=item_id,
        worktree_path=str(tmp_path),
        args=SimpleNamespace(branch="example-branch", local_verification=True),
    )


def _resolved(scope, command, covering_runs=()):
    return lambda _ctx: (scope, command, list(covering_runs))


def _git(repo, *args):
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True, capture_output=True, text=True,
    )


def _commit_all(repo, message):
    _git(repo, "add", "-A")
    _git(
        repo, "-c", "user.email=verify@example.com", "-c", "user.name=Verify",
        "commit", "-q", "--allow-empty", "-m", message,
    )
    proc = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    )
    return proc.stdout.strip()


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q")
    (tmp_path / "module.py").write_text("VALUE = 1\n")
    _commit_all(tmp_path, "seed candidate tree")
    return tmp_path


def test_run_tests_executes_registered_command_in_candidate_worktree(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path,
) -> None:
    monkeypatch.setattr(
        merge_worktree_tests,
        "_registered_verification_command",
        _resolved("full", "python3 verify_tree.py"),
    )
    seen = []

    def execute(command, **kwargs):
        seen.append((command, kwargs))
        return 0, "tree verified"

    monkeypatch.setattr(merge_worktree_tests, "_run_streaming", execute)
    assert merge_worktree_tests.run_tests(_ctx(tmp_path)) is None
    assert seen == [
        (
            ["/bin/sh", "-c", "python3 verify_tree.py"],
            {
                "cwd": str(tmp_path),
                "timeout": 1200,
                "prefix": "[verification]",
            },
        )
    ]
    output = capsys.readouterr().out
    assert "registered project verification (full)" in output


def test_run_tests_blocks_when_registered_command_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        merge_worktree_tests,
        "_registered_verification_command",
        _resolved("quick", "python3 verify_tree.py"),
    )
    monkeypatch.setattr(
        merge_worktree_tests,
        "_run_streaming",
        lambda _command, **_kwargs: (1, "runtime arity failure"),
    )
    assert merge_worktree_tests.run_tests(_ctx(tmp_path)) == (
        1, "tests failed",
    )


def test_run_tests_blocks_when_registered_command_resolution_fails(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path,
) -> None:
    def unavailable(_ctx):
        raise RuntimeError("project has no executable registered command")

    monkeypatch.setattr(
        merge_worktree_tests,
        "_registered_verification_command",
        unavailable,
    )
    assert merge_worktree_tests.run_tests(_ctx(tmp_path)) == (
        1,
        "test command unavailable",
    )
    assert "no executable registered command" in capsys.readouterr().err


def test_run_tests_skips_when_passing_run_covered_identical_tree(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    repo,
) -> None:
    covered_sha = _commit_all(repo, "restate head with an identical tree")
    head_sha = _commit_all(repo, "rebase-equivalent commit, same tree")
    assert covered_sha != head_sha

    monkeypatch.setattr(
        merge_worktree_tests,
        "_registered_verification_command",
        _resolved(
            "full",
            "python3 verify_tree.py",
            [{"run_id": 7, "head_sha": covered_sha}],
        ),
    )

    def refuse(*_args, **_kwargs):
        raise AssertionError("covered tree must not re-execute the suite")

    monkeypatch.setattr(merge_worktree_tests, "_run_streaming", refuse)
    assert merge_worktree_tests.run_tests(_ctx(repo)) is None
    output = capsys.readouterr().out
    assert "skipping registered verification" in output
    assert "run 7" in output


def test_run_tests_executes_when_covered_tree_differs(
    monkeypatch: pytest.MonkeyPatch,
    repo,
) -> None:
    covered_sha = _commit_all(repo, "tree before the integration diff")
    (repo / "module.py").write_text("VALUE = 2\n")
    _commit_all(repo, "integration changed the tree")

    monkeypatch.setattr(
        merge_worktree_tests,
        "_registered_verification_command",
        _resolved(
            "full",
            "python3 verify_tree.py",
            [{"run_id": 7, "head_sha": covered_sha}],
        ),
    )
    executed = []
    monkeypatch.setattr(
        merge_worktree_tests,
        "_run_streaming",
        lambda command, **_kwargs: (executed.append(command), (0, "ok"))[1],
    )
    assert merge_worktree_tests.run_tests(_ctx(repo)) is None
    assert executed == [["/bin/sh", "-c", "python3 verify_tree.py"]]


def test_run_tests_executes_when_covered_commit_is_unknown(
    monkeypatch: pytest.MonkeyPatch,
    repo,
) -> None:
    monkeypatch.setattr(
        merge_worktree_tests,
        "_registered_verification_command",
        _resolved(
            "full",
            "python3 verify_tree.py",
            [{"run_id": 7, "head_sha": "f" * 40}],
        ),
    )
    executed = []
    monkeypatch.setattr(
        merge_worktree_tests,
        "_run_streaming",
        lambda command, **_kwargs: (executed.append(command), (0, "ok"))[1],
    )
    assert merge_worktree_tests.run_tests(_ctx(repo)) is None
    assert executed == [["/bin/sh", "-c", "python3 verify_tree.py"]]


def test_run_tests_executes_when_worktree_is_not_a_repository(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        merge_worktree_tests,
        "_registered_verification_command",
        _resolved(
            "full",
            "python3 verify_tree.py",
            [{"run_id": 7, "head_sha": "f" * 40}],
        ),
    )
    executed = []
    monkeypatch.setattr(
        merge_worktree_tests,
        "_run_streaming",
        lambda command, **_kwargs: (executed.append(command), (0, "ok"))[1],
    )
    assert merge_worktree_tests.run_tests(_ctx(tmp_path)) is None
    assert executed == [["/bin/sh", "-c", "python3 verify_tree.py"]]
