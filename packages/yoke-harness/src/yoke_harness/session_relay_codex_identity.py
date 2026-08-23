"""Exact Codex thread/session correlation through the native app server."""

from __future__ import annotations

import os
from pathlib import Path

from yoke_harness.session_relay_codex_app_server import (
    CodexAppServerError,
    _Client,
    _identity,
    _thread,
)


def resolve_thread_identity(
    thread_id: str,
    checkout: Path,
    *,
    binary: str = "codex",
    timeout: float = 15.0,
) -> tuple[str, str] | None:
    """Read the vendor's thread/session pair; never scan a time window."""
    env = dict(os.environ)
    env["YOKE_EXECUTOR"] = "codex"
    client: _Client | None = None
    try:
        client = _Client(binary, checkout, env, timeout)
        return _identity(
            _thread(
                client.request(
                    "thread/read", {"threadId": thread_id, "includeTurns": False}
                )
            )
        )
    except CodexAppServerError:
        return None
    finally:
        if client is not None:
            client.close()


__all__ = ["resolve_thread_identity"]
