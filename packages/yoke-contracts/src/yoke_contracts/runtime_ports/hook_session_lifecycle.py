"""Runtime interface for hook session lifecycle."""

from __future__ import annotations

from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class HookSessionLifecycle(Protocol):
    """Hook operations supplied by the executing adapter."""

    env_file_session_id: Any
    persist_session_env: Any
    sync_session_main_checkout: Any


def get_hook_session_lifecycle() -> HookSessionLifecycle:
    return cast(HookSessionLifecycle, load_port("hook_session_lifecycle", HookSessionLifecycle))
