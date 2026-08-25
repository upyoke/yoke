"""Tests for the session and run namespaces of Yoke scratch paths."""

from __future__ import annotations

import pytest

from yoke_core.domain import project_scratch_dir as scratch
from yoke_core.domain import project_scratch_segments as segments


def _no_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    from yoke_contracts.session_identity import AMBIENT_ENV_VARS

    for key in AMBIENT_ENV_VARS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(
        "yoke_core.domain.session_process_anchors.resolve_session_from_ancestry",
        lambda: None,
    )
    monkeypatch.setattr(
        "yoke_contracts.cursor_session_map.resolve_mapped_session_id",
        lambda directory, env=None: None,
    )


def _no_harness(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in segments.HARNESS_PRESENCE_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_harness_presence_reads_markers_not_the_process_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A launched worker's ancestors are pooled daemon processes, so the
    marker is the only signal that reports it as a harness session."""
    _no_harness(monkeypatch)
    assert segments.under_harness_session() is False

    monkeypatch.setenv("CLAUDECODE", "1")
    assert segments.under_harness_session() is True


def test_required_segment_refuses_the_placeholder_inside_a_harness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_identity(monkeypatch)
    _no_harness(monkeypatch)
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "cli")

    with pytest.raises(segments.ScratchSessionIdentityError) as caught:
        segments.require_resolved_session_segment()

    assert segments.DEFAULT_SESSION_SEGMENT in str(caught.value)


def test_required_segment_keeps_the_placeholder_for_an_operator_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_identity(monkeypatch)
    _no_harness(monkeypatch)

    assert (
        segments.require_resolved_session_segment() == segments.DEFAULT_SESSION_SEGMENT
    )


def test_required_segment_returns_the_resolved_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("YOKE_SESSION_ID", "resolved-session")

    assert segments.require_resolved_session_segment() == "resolved-session"


def test_watcher_capture_refuses_a_path_the_session_guard_would_deny(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Minting under the placeholder produced a capture the session-cwd
    guard then refused, reporting the path instead of the identity gap."""
    _no_identity(monkeypatch)
    _no_harness(monkeypatch)
    monkeypatch.setenv("CLAUDECODE", "1")

    with pytest.raises(scratch.ScratchSessionIdentityError):
        scratch.mint_watcher_capture_pair("pytest")


def test_watcher_capture_lands_under_the_resolved_session(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(scratch.ENV_KEY, str(tmp_path))
    monkeypatch.setenv("YOKE_SESSION_ID", "worker-session")
    monkeypatch.setenv("YOKE_RUN_ID", "run-1")

    raw, progress = scratch.mint_watcher_capture_pair("pytest", project="yoke")

    expected = (
        tmp_path
        / "yoke"
        / "sessions"
        / "worker-session"
        / "runs"
        / "run-1"
        / "watcher-captures"
    )
    assert raw.parent == expected
    assert progress.parent == expected
    assert raw.name.endswith(".log") and ".raw." in raw.name
    assert ".progress." in progress.name


def test_run_segment_prefers_a_declared_run_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in segments.RUN_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    assert segments.run_segment().startswith("pid-")

    monkeypatch.setenv("GITHUB_RUN_ID", "12345")
    assert segments.run_segment() == "12345"


@pytest.mark.parametrize("value", ["", "  ", ".", "..", "/abs", "a/b", "../x"])
def test_safe_segment_rejects_anything_that_is_not_one_path_part(
    value: str,
) -> None:
    with pytest.raises(ValueError):
        segments.safe_segment(value)
