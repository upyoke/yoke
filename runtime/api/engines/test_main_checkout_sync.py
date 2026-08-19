"""A landing may advance only a clean main checkout on its target branch."""

from __future__ import annotations

import subprocess

from yoke_core.engines.main_checkout_sync import (
    fast_forward_main_checkout,
    sync_main_checkout_at_session_start,
)


def _result(returncode: int = 0, stdout: str = "", stderr: str = ""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def _runner(responses, calls):
    def run(command, **_kwargs):
        calls.append(command)
        return responses.pop(0)
    return run


def test_clean_target_checkout_uses_only_pull_for_the_mutation():
    calls: list[list[str]] = []
    warning = fast_forward_main_checkout(
        "/tmp/repo", "main",
        run=_runner([_result(stdout="main\n"), _result(), _result()], calls),
    )

    assert warning == ""
    assert calls[-1] == [
        "git", "-C", "/tmp/repo", "pull", "--ff-only", "origin", "main",
    ]


def test_dirty_checkout_is_not_touched():
    calls: list[list[str]] = []
    warning = fast_forward_main_checkout(
        "/tmp/repo", "main",
        run=_runner([_result(stdout="main\n"), _result(stdout=" M local.py\n")], calls),
    )

    assert warning == "main checkout not fast-forwarded: checkout has local changes"
    assert all("pull" not in call for call in calls)


def test_off_branch_checkout_is_not_touched():
    calls: list[list[str]] = []
    warning = fast_forward_main_checkout(
        "/tmp/repo", "main",
        run=_runner([_result(stdout="feature\n")], calls),
    )

    assert warning == "main checkout not fast-forwarded: checkout is on feature, not main"
    assert all("pull" not in call for call in calls)


def test_untracked_files_do_not_block_the_fast_forward():
    calls: list[list[str]] = []
    warning = fast_forward_main_checkout(
        "/tmp/repo", "main",
        run=_runner([_result(stdout="main\n"), _result(), _result()], calls),
    )

    assert warning == ""
    assert calls[1] == [
        "git", "-C", "/tmp/repo", "status", "--porcelain", "--untracked-files=no",
    ]
    assert calls[-1][-4:] == ["pull", "--ff-only", "origin", "main"]


def test_session_start_sync_uses_origin_head_and_does_not_raise():
    calls: list[list[str]] = []
    warning = sync_main_checkout_at_session_start(
        "/tmp/repo",
        run=_runner(
            [
                _result(stdout="origin/main\n"),
                _result(stdout="main\n"),
                _result(),
                _result(),
            ],
            calls,
        ),
    )

    assert warning == ""
    assert calls[0][-3:] == [
        "symbolic-ref", "--short", "refs/remotes/origin/HEAD",
    ]


def test_failed_fast_forward_is_a_named_advisory():
    warning = fast_forward_main_checkout(
        "/tmp/repo", "main",
        run=_runner(
            [_result(stdout="main\n"), _result(), _result(1, stderr="not possible\n")],
            [],
        ),
    )

    assert warning == "main checkout not fast-forwarded: not possible"
