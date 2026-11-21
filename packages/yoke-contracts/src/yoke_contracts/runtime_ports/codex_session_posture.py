"""Runtime interface for codex session posture."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class CodexSessionPosture(Protocol):
    codex_session_posture: Callable[..., Any]


def get_codex_session_posture() -> CodexSessionPosture:
    return cast(CodexSessionPosture, load_port("codex_session_posture", CodexSessionPosture))
