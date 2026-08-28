"""Cursor identity detection across both identity module copies.

The executor/provider/entrypoint detection logic exists in two deliberate
copies — the in-tree hook helpers and the product-wheel runtime module —
and both must classify Cursor identically.
"""

from __future__ import annotations

import pytest

import yoke_core.hooks.helpers_identity as tree_identity
import yoke_harness.hooks.identity_runtime as wheel_identity

BOTH = pytest.mark.parametrize("identity", [tree_identity, wheel_identity])


@pytest.fixture(autouse=True)
def _clean_identity_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "YOKE_EXECUTOR", "CODEX_THREAD_ID", "CLAUDE_CODE_SESSION_ID",
        "CLAUDE_CODE_ENTRYPOINT", "CURSOR_CONVERSATION_ID",
        "CURSOR_TRANSCRIPT_PATH", "CURSOR_INVOKED_AS",
    ):
        monkeypatch.delenv(var, raising=False)


@BOTH
def test_is_cursor_matches_coarse_and_surfaces(identity) -> None:
    assert identity.is_cursor("cursor")
    assert identity.is_cursor("cursor-cli")
    assert identity.is_cursor("cursor-desktop")
    assert not identity.is_cursor("codex")
    assert not identity.is_cursor("claude-code")
    assert not identity.is_cursor(None)


@BOTH
def test_canonical_harness_id_maps_cursor(identity) -> None:
    assert identity.canonical_harness_id("cursor") == "cursor"
    assert identity.canonical_harness_id("cursor-cli") == "cursor"
    assert identity.canonical_harness_id("codex-desktop") == "codex"
    with pytest.raises(ValueError):
        identity.canonical_harness_id("aider")


@BOTH
def test_compose_executor_from_entrypoint(identity) -> None:
    assert identity.compose_executor_from_entrypoint("cursor", "cursor-cli") == "cursor-cli"
    assert identity.compose_executor_from_entrypoint("cursor", "desktop") == "cursor-desktop"
    assert identity.compose_executor_from_entrypoint("cursor", None) == "cursor"


@BOTH
def test_detect_executor_cursor_env(identity, monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("YOKE_EXECUTOR", "CODEX_THREAD_ID", "CLAUDE_CODE_ENTRYPOINT"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("CURSOR_INVOKED_AS", "cursor-agent")
    assert identity.detect_executor() == "cursor-cli"
    monkeypatch.delenv("CURSOR_INVOKED_AS")
    monkeypatch.setenv("CURSOR_TRANSCRIPT_PATH", "/x/abc/abc.jsonl")
    assert identity.detect_executor() == "cursor-desktop"
    # Pin still wins over ambient Cursor markers.
    monkeypatch.setenv("YOKE_EXECUTOR", "cursor")
    assert identity.detect_executor() == "cursor"


@BOTH
def test_detect_provider_cursor_is_provider_multiplexing(
    identity, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("YOKE_PROVIDER", raising=False)
    assert identity.detect_provider("cursor-cli") == "cursor"
    assert identity.detect_provider("codex") == "openai"
    assert identity.detect_provider("claude-code") == "anthropic"


@BOTH
def test_detect_entrypoint_cursor_surfaces(
    identity, monkeypatch: pytest.MonkeyPatch
) -> None:
    for var in ("CLAUDE_CODE_ENTRYPOINT", "CODEX_THREAD_ID"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("CURSOR_INVOKED_AS", "cursor-agent")
    assert identity.detect_entrypoint() == "cursor-cli"
    monkeypatch.delenv("CURSOR_INVOKED_AS")
    monkeypatch.setenv("CURSOR_TRANSCRIPT_PATH", "/x/abc/abc.jsonl")
    assert identity.detect_entrypoint() == "cursor-desktop"


@BOTH
def test_cursor_surface_entrypoint_defaults_to_desktop_without_transcript(
    identity, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The IDE surface resolves even before the transcript path exists.

    Cursor does not export ``CURSOR_TRANSCRIPT_PATH`` for a session's first
    hook events, which is exactly when session registration runs. The
    surface resolver must therefore key on the CLI discriminator alone and
    treat its absence as the IDE surface.
    """
    monkeypatch.delenv("CURSOR_INVOKED_AS", raising=False)
    monkeypatch.delenv("CURSOR_TRANSCRIPT_PATH", raising=False)
    assert identity.cursor_surface_entrypoint() == "cursor-desktop"
    monkeypatch.setenv("CURSOR_INVOKED_AS", "cursor-agent")
    assert identity.cursor_surface_entrypoint() == "cursor-cli"


@BOTH
def test_cursor_surface_entrypoint_ignores_unrecognized_invoked_as(
    identity, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CURSOR_TRANSCRIPT_PATH", raising=False)
    monkeypatch.setenv("CURSOR_INVOKED_AS", "something-else")
    assert identity.cursor_surface_entrypoint() == "cursor-desktop"


@BOTH
def test_detect_executor_conversation_id_only_is_cursor_desktop(
    identity, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CURSOR_CONVERSATION_ID", "conv-ide-shell")
    assert identity.detect_executor() == "cursor-desktop"


@BOTH
def test_detect_executor_claude_session_wins_over_conversation_id(
    identity, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "claude-nested")
    monkeypatch.setenv("CURSOR_CONVERSATION_ID", "conv-ide-shell")
    assert identity.detect_executor() == "claude-code"


def test_cursor_payload_model_prefers_tiered_model_over_bare_id(tmp_path) -> None:
    # No conversation store for this id, so the payload is the only source.
    assert wheel_identity.cursor_payload_model(
        {"session_id": "no-such-conversation", "model_id": "grok-4.6",
         "model": "cursor-grok-4.6-xhigh"}
    ) == "cursor-grok-4.6-xhigh"


def test_cursor_payload_model_records_bare_model_when_no_tier() -> None:
    assert wheel_identity.cursor_payload_model(
        {"session_id": "no-such-conversation", "model": "grok-4.6"}
    ) == "grok-4.6"
    assert wheel_identity.cursor_payload_model(
        {"session_id": "no-such-conversation", "model_id": "grok-4.6"}
    ) == "grok-4.6"


@BOTH
def test_detect_executor_codex_thread_wins_over_conversation_id(
    identity, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_THREAD_ID", "codex-nested")
    monkeypatch.setenv("CURSOR_CONVERSATION_ID", "conv-ide-shell")
    assert identity.is_codex(identity.detect_executor())
