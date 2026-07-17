"""Tests for the Claude first-prompt marker primitives."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import project_scratch_dir as scratch
from runtime.harness.hook_runner import session_dispatch_first_prompt as fp


@pytest.fixture
def scoped_scratch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Pin the scratch root to a unique tmp directory per test."""

    monkeypatch.setenv(scratch.ENV_KEY, str(tmp_path))
    return tmp_path


def test_claude_prompt_marker_path_is_process_stable(scoped_scratch: Path) -> None:
    marker = fp.claude_prompt_marker_path("abc-123")

    assert marker.is_absolute()
    assert marker.parent.name == "hook-markers"
    # Fire-once markers coordinate across hook processes: no per-session
    # or per-run segments may appear in the path.
    assert "sessions" not in marker.parts
    assert "runs" not in marker.parts
    assert marker.name == "claude-prompt-abc-123"


def test_is_first_prompt_true_when_marker_missing(scoped_scratch: Path) -> None:
    assert fp.is_first_prompt("fresh-session") is True


def test_mark_first_prompt_arms_marker(scoped_scratch: Path) -> None:
    fp.mark_first_prompt("session-xyz")

    assert fp.claude_prompt_marker_path("session-xyz").exists()
    assert fp.is_first_prompt("session-xyz") is False


def test_first_prompt_claude_arms_on_first_call(scoped_scratch: Path) -> None:
    sid = "claude-session-A"

    assert fp.first_prompt(sid, codex=False) is True
    assert fp.first_prompt(sid, codex=False) is False


def test_first_prompt_codex_routes_to_codex_marker(
    scoped_scratch: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Codex routing must arm the codex-prompt marker, not the claude one."""

    sid = "codex-session-B"

    # First call returns True and arms the codex prompt marker.
    assert fp.first_prompt(sid, codex=True) is True
    # The claude marker for the same session_id should still be unarmed.
    assert fp.is_first_prompt(sid) is True
    # Second codex call returns False (already armed).
    assert fp.first_prompt(sid, codex=True) is False


def test_unique_sessions_have_distinct_marker_paths(scoped_scratch: Path) -> None:
    a = fp.claude_prompt_marker_path("session-A")
    b = fp.claude_prompt_marker_path("session-B")

    assert a != b
    assert a.parent == b.parent  # both under hook-markers


def test_mark_first_prompt_swallows_oserror(
    scoped_scratch: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hook paths must never crash on filesystem weirdness."""

    def boom_touch(self, *args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "touch", boom_touch)
    # Must not raise.
    fp.mark_first_prompt("any-session")
