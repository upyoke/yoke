"""Standalone close-out advances the project main checkout after landing."""

from __future__ import annotations

from yoke_core.domain import standalone_item_merge as merge
from yoke_core.domain import standalone_item_merge_post_push as post_push


def test_completed_standalone_landing_fast_forwards_main(monkeypatch):
    monkeypatch.setattr(merge.git, "git_out", lambda *_a: "m" * 40)
    monkeypatch.setattr(merge.git, "publish", lambda *_a: (True, ""))
    monkeypatch.setattr(merge.git, "has_remote", lambda *_a: True)
    monkeypatch.setattr(merge, "stamp_merged_at", lambda *_a: None)
    monkeypatch.setattr(merge.receipts, "record", lambda *_a, **_k: "")
    monkeypatch.setattr(
        post_push, "await_post_push_checks",
        lambda *_a: post_push.PostPushVerdict("no_checks"),
    )
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        post_push, "fast_forward_main_checkout",
        lambda root, target: calls.append((root, target)) or "",
    )

    outcome = merge._complete(
        item_id=7, branch="item", target="main", repo_root="/tmp/repo",
        project="yoke", commit_sha="c" * 40, touched=("file.py",), already=False,
    )

    assert outcome.ok
    assert calls == [("/tmp/repo", "main")]
