"""Integrated-candidate verification through registered project commands."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from yoke_core.engines import merge_worktree_tests


def _ctx(tmp_path, *, project="example", item_id="42"):
    return SimpleNamespace(
        project=project,
        item_id=item_id,
        worktree_path=str(tmp_path),
    )


def test_run_tests_executes_registered_command_in_candidate_worktree(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path,
) -> None:
    monkeypatch.setattr(
        merge_worktree_tests,
        "_registered_verification_command",
        lambda _ctx: ("full", "python3 verify_tree.py"),
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
        lambda _ctx: ("quick", "python3 verify_tree.py"),
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
