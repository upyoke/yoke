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
    startup = ("Required authority and trust instructions. " * 50).rstrip()
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
    assert len(rendered.encode("utf-8")) <= min(INLINE_CONTEXT_BYTES.values())
    assert ("Current branch:" in rendered) is (branch == "main")
