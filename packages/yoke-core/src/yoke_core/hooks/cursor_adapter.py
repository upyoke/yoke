"""Cursor `AdapterCapability` instance consumed by the shared hook runner.

The adapter is data-only: it points at the Cursor payload parser (which
canonicalizes ``Shell`` -> ``Bash`` and synthesizes the Bash tool shape for
``beforeShellExecution``/``afterShellExecution`` payloads) and the
Cursor-shaped decision renderer.

No chain omissions are declared: Cursor runs the same universal chains
as Claude and Codex. Cursor has no allow-time ``additional_context``
channel on ``preToolUse``, but that constraint is owned by the decision
renderer (advisory-only output renders as a plain allow), and the
Monitor / ScheduleWakeup / TaskOutput matchers never render into Cursor
hook config at all (no such tools exist there).

The runner's `__main__` lazily imports this module for the detected
harness; no policy-evaluation code lives here.
"""

from __future__ import annotations

from yoke_core.hooks.cursor_payload import parse_payload
from yoke_core.hooks.adapter_capability import AdapterCapability
from yoke_core.hooks.decision_render import render_cursor_decision

__all__ = ["CAPABILITY"]


CAPABILITY: AdapterCapability = AdapterCapability(
    family="cursor",
    payload_parser=parse_payload,
    decision_renderer=render_cursor_decision,
    apply_patch_chain_omissions=frozenset(),
    pretool_omissions=frozenset(),
)
