"""Runtime interface for identity codex runtime."""

from __future__ import annotations

from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class IdentityCodexRuntime(Protocol):
    """Hook operations supplied by the executing adapter."""

    _codex_entrypoint_from_transcript: Any
    _codex_model_from_transcript: Any


def get_identity_codex_runtime() -> IdentityCodexRuntime:
    return cast(IdentityCodexRuntime, load_port("identity_codex_runtime", IdentityCodexRuntime))
