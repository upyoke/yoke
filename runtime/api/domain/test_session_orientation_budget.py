"""Optional Git context must not crowd startup instructions out of a hook."""

from pathlib import Path

import pytest

from yoke_contracts.hook_inline_context import INLINE_CONTEXT_BYTES
from yoke_core.domain import session_orientation as orientation


@pytest.mark.parametrize(
    "branch",
    ["main", "gh-readonly-queue/main/" + "x" * 2000],
    ids=["short-branch", "long-queue-branch"],
)
def test_long_git_metadata_preserves_the_startup_block(monkeypatch, branch):
    root = Path("/checkout")
    startup = ("Required authority and trust instructions. " * 15).rstrip()
    monkeypatch.setattr(orientation, "_advisory_lines", lambda _: [])
    monkeypatch.setattr(orientation, "_startup_block_lines", lambda: ["", startup])
    monkeypatch.setattr(
        orientation,
        "_git_line",
        lambda _, args: branch if args[0] == "branch" else "abc1234 " + "長" * 1000,
    )

    rendered = orientation.render_orientation({"session_id": "test-session"}, root)

    assert startup in rendered
    assert "Your Session: test-session" in rendered
    assert "Root: /checkout" in rendered
    assert "Recent commit:" not in rendered
    assert len(rendered.encode("utf-8")) <= min(1200, min(INLINE_CONTEXT_BYTES.values()))
    assert ("Current branch:" in rendered) is (branch == "main")


def test_bound_project_orientation_is_under_twelve_hundred_bytes(monkeypatch):
    monkeypatch.setattr(orientation, "_advisory_lines", lambda _: [])
    monkeypatch.setattr(orientation, "_git_line", lambda *_: "main")
    body = orientation.render_orientation({"session_id": "a" * 36}, Path("/checkout"))
    assert len(body.encode()) < 1200


def test_long_metadata_uses_the_project_orientation_budget(monkeypatch):
    monkeypatch.setattr(orientation, "_advisory_lines", lambda _: [])
    monkeypatch.setattr(orientation, "_git_line", lambda _, args:
                        "topic-" + "x" * 900 if args[0] == "branch"
                        else "a" * 1000)
    body = orientation.render_orientation({"session_id": "a" * 36}, Path("/checkout"))
    assert len(body.encode()) <= 1200
