"""Executor-string -> ``AdapterCapability`` resolution.

Shared by the CLI entry (``__main__`` resolves the executor by detection)
and the remote entry (``/v1/hooks/evaluate`` honors the REQUEST's executor
verbatim — the server never re-detects). Any ``codex``-prefixed executor
maps to the Codex adapter; everything else maps to Claude. ``dry_run=True``
tolerates a missing harness adapter import by substituting a stub
capability so the printed chain stays inspectable.
"""

from __future__ import annotations

import json
from typing import Any

from yoke_core.hooks.adapter_capability import AdapterCapability
from yoke_core.hooks.decision_render import (
    render_claude_decision,
    render_codex_decision,
    render_cursor_decision,
)


__all__ = ["resolve_capability"]


def _stub_payload_parser(stdin_data: str) -> dict[str, Any]:
    if not stdin_data:
        return {}
    try:
        data = json.loads(stdin_data)
    except (json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def resolve_capability(executor: str, dry_run: bool = False) -> AdapterCapability:
    """Return the harness ``AdapterCapability`` for *executor*."""
    if executor.startswith("codex"):
        family = "codex"
    elif executor.startswith("cursor"):
        family = "cursor"
    else:
        family = "claude"
    try:
        if family == "codex":
            from yoke_core.hooks.codex_adapter import CAPABILITY  # noqa: PLC0415
        elif family == "cursor":
            from yoke_core.hooks.cursor_adapter import CAPABILITY  # noqa: PLC0415
        else:
            from yoke_core.hooks.claude_adapter import CAPABILITY  # noqa: PLC0415
        return CAPABILITY
    except ImportError:
        if not dry_run:
            raise
    renderer = {
        "codex": render_codex_decision,
        "cursor": render_cursor_decision,
    }.get(family, render_claude_decision)
    return AdapterCapability(
        family=family,
        payload_parser=_stub_payload_parser,
        decision_renderer=renderer,
    )
