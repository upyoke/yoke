"""Runtime interface for setup facts summary."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class SetupFactsSummary(Protocol):
    """Operations and values supplied by the executing adapter."""

    orientation_lines: Callable[..., Any]


def get_setup_facts_summary() -> SetupFactsSummary:
    return cast(SetupFactsSummary, load_port("setup_facts_summary", SetupFactsSummary))
