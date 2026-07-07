"""Shared types for the structured-API adapter inventory modules.

Owns the :class:`AdapterEntry` dataclass and helpers so the per-family
entry modules and the main inventory module can share one shape without
circular imports.
"""

from __future__ import annotations

from dataclasses import dataclass


AGENT_PATH_VALUES = frozenset({"direct", "skill-orchestrated", "operator-only"})


@dataclass(frozen=True)
class AdapterEntry:
    """One retained CLI adapter -> function id binding."""

    function_id: str
    cli_invocation: str
    notes: str = ""
    read_shape: bool = False
    agent_path: str = "direct"
    canonical_skill_invocation: str = ""
    direct_use_caveat: str = ""


def read_entry(**kwargs) -> AdapterEntry:
    return AdapterEntry(**kwargs, read_shape=True)


__all__ = ["AGENT_PATH_VALUES", "AdapterEntry", "read_entry"]
