"""Cursor identity detection across both identity module copies.

The executor/provider/entrypoint detection logic exists in two deliberate
copies — the in-tree hook helpers and the product-wheel runtime module —
and both must classify Cursor identically.
"""

from __future__ import annotations

import pytest

import runtime.harness.hook_helpers_identity as tree_identity
import yoke_harness.hooks.identity_runtime as wheel_identity

BOTH = pytest.mark.parametrize("identity", [tree_identity, wheel_identity])


@BOTH
def test_is_cursor_matches_coarse_and_surfaces(identity) -> None:
    assert identity.is_cursor("cursor")
    assert identity.is_cursor("cursor-cli")
    assert identity.is_cursor("cursor-ide")
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
    assert identity.compose_executor_from_entrypoint("cursor", "ide") == "cursor-ide"
    assert identity.compose_executor_from_entrypoint("cursor", None) == "cursor"


@BOTH
def test_detect_executor_cursor_env(identity, monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("YOKE_EXECUTOR", "CODEX_THREAD_ID", "CLAUDE_CODE_ENTRYPOINT"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("CURSOR_INVOKED_AS", "cursor-agent")
    assert identity.detect_executor() == "cursor-cli"
    monkeypatch.delenv("CURSOR_INVOKED_AS")
    monkeypatch.setenv("CURSOR_TRANSCRIPT_PATH", "/x/abc/abc.jsonl")
    assert identity.detect_executor() == "cursor-ide"
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
    assert identity.detect_entrypoint() == "cursor-ide"
