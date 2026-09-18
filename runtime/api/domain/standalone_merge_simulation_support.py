"""Shared scaffolding for suites that drive the merge with no control plane.

These suites run the standalone merge boundary -- some of it through
``standalone_item_merge_cli`` end to end -- against a real git checkout
while stubbing the collaborators that would otherwise reach a database.
Plain functions rather than fixtures, so each suite binds them to its own
fixture names without shadowing them.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from yoke_core.domain import item_merge_receipts as receipts
from yoke_core.domain import standalone_item_merge as sim


def git(repo: Path, *args: str) -> str:
    """Run one git command in ``repo`` and return its trimmed stdout."""
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def merge(repo: Path, *, item_id: int = 7, branch: str = "ITEM-1"):
    """Land ``branch`` through the standalone engine, bound to its head."""
    return sim.merge_standalone_branch(
        project="yoke",
        item_id=item_id,
        branch=branch,
        target="main",
        repo_root=str(repo),
        commit_sha=git(repo, "rev-parse", branch),
    )


def make_checkout(tmp_path: Path) -> Path:
    """A checkout with a base branch and one item branch ahead of it."""
    root = tmp_path / "checkout"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.email", "test@test.com")
    git(root, "config", "user.name", "Test")
    (root / "base.txt").write_text("base\n")
    git(root, "add", "base.txt")
    git(root, "commit", "-m", "base")

    git(root, "checkout", "-b", "ITEM-1")
    (root / "feature.txt").write_text("feature\n")
    git(root, "add", "feature.txt")
    git(root, "commit", "-m", "feature")
    git(root, "checkout", "main")
    return root


def stub_receipts(monkeypatch: Any) -> None:
    """Keep a suite on git state alone.

    The durable receipt and the retry paths that read it back have their own
    suite (``test_standalone_item_merge_crash_retry``); here an unstubbed
    ledger would only add control-plane calls to assertions about the merge.
    """
    monkeypatch.setattr(receipts, "record", lambda *_a, **_k: "")
    monkeypatch.setattr(receipts, "load", lambda *_a, **_k: None)


def stub_candidate_review(monkeypatch: Any) -> None:
    """Answer the candidate review the way an unselected posture does.

    The gate asks the control plane about the exact head before either
    landing route; an item that selects no review is what these cases are
    about, and the gate has its own suites.
    """
    from yoke_core.domain import merge_queue_route_selection as selection

    monkeypatch.setattr(selection, "candidate_review_refusal", lambda **_kw: "")


__all__ = [
    "git",
    "make_checkout",
    "merge",
    "stub_candidate_review",
    "stub_receipts",
]
