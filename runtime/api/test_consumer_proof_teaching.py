"""Merge routes carry no consumer-proof dispatch hook."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_merge_routes_have_no_consumer_dispatch_hook():
    for relative in (
        "packages/yoke-core/src/yoke_core/engines/merge_worktree_execute.py",
        "packages/yoke-core/src/yoke_core/domain/merge_queue_route.py",
    ):
        assert "require_consumer_proof" not in (ROOT / relative).read_text()
