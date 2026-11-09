"""Runtime interface for hook client facts."""

from __future__ import annotations

from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class HookClientFacts(Protocol):
    """Hook operations supplied by the executing adapter."""

    collect_client_facts: Any
    event_chain: Any


def get_hook_client_facts() -> HookClientFacts:
    return cast(HookClientFacts, load_port("hook_client_facts", HookClientFacts))
