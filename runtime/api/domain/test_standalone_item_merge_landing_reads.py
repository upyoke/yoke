"""Regression checks for standalone item merge landing reads."""

from __future__ import annotations

from yoke_core.domain import standalone_item_merge_git as git

from runtime.api.domain.test_standalone_item_merge_close_out import (
    LANE_SHA as LANE_SHA,
    SimpleNamespace as SimpleNamespace,
    landed as landed,
)


def test_is_landed_consults_the_remote_before_refusing(monkeypatch):
    commands: list = []

    def fake_git(repo_root, *args):
        commands.append(list(args))
        landed = args[:2] == ("merge-base", "--is-ancestor")
        remote_ref = landed and args[3] == "origin/main"
        return SimpleNamespace(
            returncode=0 if remote_ref else 1,
            stdout="origin\n",
            stderr="",
        )

    monkeypatch.setattr(git, "_git", fake_git)
    monkeypatch.setattr(git, "git_out", lambda repo_root, *args: "origin")

    assert git.is_landed("/repo", LANE_SHA, "main") is True
    assert ["fetch", "origin", "main"] in commands


def test_is_landed_is_false_without_a_commit(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("no git read is needed without a commit")

    monkeypatch.setattr(git, "_git", forbidden)

    assert git.is_landed("/repo", "", "main") is False
