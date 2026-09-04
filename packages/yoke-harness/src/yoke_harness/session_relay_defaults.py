"""Lazy native adapter construction for a relay-leased surface."""

from __future__ import annotations

from functools import lru_cache

from yoke_harness.session_launch_handoff import stage_launch_attestation
from yoke_harness.session_relay_runtime import RelayAdapter, register_relay_adapter


@lru_cache(maxsize=1)
def _codex_adapter() -> RelayAdapter:
    from yoke_harness.session_relay_codex import build_codex_relay_adapter
    from yoke_harness.session_relay_codex_app_server import CodexAppServerTransport
    from yoke_harness.session_relay_codex_cli import CodexCliTransport

    return build_codex_relay_adapter(
        cli_transport=CodexCliTransport(),
        desktop_transport=CodexAppServerTransport(),
    )


@lru_cache(maxsize=1)
def _cursor_adapter() -> RelayAdapter:
    from yoke_harness.session_relay_cursor import build_cursor_adapter
    from yoke_harness.session_relay_cursor_cli import CursorCliTransport
    from yoke_harness.session_relay_cursor_identity import conversation_map_lookup

    return build_cursor_adapter(
        subprocess_port=CursorCliTransport(),
        identity_lookup=conversation_map_lookup,
        attestation_handoff=stage_launch_attestation,
    )


def _claude_cli_adapter(context):
    from yoke_harness.session_relay_claude import run_claude_cli_adapter

    return run_claude_cli_adapter(context)


def _claude_unsupported_adapter(context):
    from yoke_harness.session_relay_claude import unsupported_claude_route

    return unsupported_claude_route(context)


def register_default_relay_adapter(surface: str) -> bool:
    """Register exactly one closed adapter, leaving unknown surfaces absent."""
    if surface in {"codex-cli", "codex-desktop"}:
        adapter = _codex_adapter()
    elif surface == "cursor-cli":
        adapter = _cursor_adapter()
    elif surface == "claude-cli":
        adapter = _claude_cli_adapter
    elif surface in {"claude-desktop", "claude-vscode"}:
        adapter = _claude_unsupported_adapter
    else:
        return False
    register_relay_adapter(surface, adapter)
    return True


__all__ = ["register_default_relay_adapter"]
