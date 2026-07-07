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

from runtime.harness.hook_runner.adapter_capability import AdapterCapability
from runtime.harness.hook_runner.decision_render import (
    render_claude_decision,
    render_codex_decision,
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
    family = "codex" if executor.startswith("codex") else "claude"
    try:
        if family == "codex":
            from runtime.harness.codex.adapter import CAPABILITY  # noqa: PLC0415
        else:
            from runtime.harness.claude.adapter import CAPABILITY  # noqa: PLC0415
        return CAPABILITY
    except ImportError:
        if not dry_run:
            raise
    renderer = render_codex_decision if family == "codex" else render_claude_decision
    return AdapterCapability(
        family=family,
        events=frozenset(),
        payload_parser=_stub_payload_parser,
        decision_renderer=renderer,
    )
