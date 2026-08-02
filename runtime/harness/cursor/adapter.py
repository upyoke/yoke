"""Cursor `AdapterCapability` instance consumed by the shared hook runner.

The adapter is data-only: it points at the Cursor payload parser (which
canonicalizes ``Shell`` -> ``Bash`` and synthesizes the Bash tool shape for
``beforeShellExecution``/``afterShellExecution`` payloads) and the
Cursor-shaped decision renderer.

``pretool_omissions`` drops the advisory-only hint modules from the
PreToolUse chains: Cursor has no allow-time ``additional_context`` channel
on ``preToolUse`` (context injection lands on ``sessionStart`` and
``postToolUse`` only), so an allow-with-advisory renders as a plain allow
and the hint would be silently discarded. Omitting the modules keeps the
chain evaluation honest about what the harness can deliver. The Monitor /
ScheduleWakeup / TaskOutput matchers never render into Cursor hook config
at all (no such tools exist there), so their chains need no omissions.

The runner's `__main__` lazily imports this module for the detected
harness; no policy-evaluation code lives here.
"""

from __future__ import annotations

from runtime.harness.cursor.cursor_hooks_payload import parse_payload
from runtime.harness.hook_runner.adapter_capability import AdapterCapability
from runtime.harness.hook_runner.decision_render import render_cursor_decision

__all__ = ["CAPABILITY"]


CAPABILITY: AdapterCapability = AdapterCapability(
    family="cursor",
    payload_parser=parse_payload,
    decision_renderer=render_cursor_decision,
    apply_patch_chain_omissions=frozenset(),
    pretool_omissions=frozenset(
        {
            "yoke_core.domain.hint_monitor_relay",
        }
    ),
    subprocess_modules=frozenset(
        {
            "yoke_core.domain.observe",
            "yoke_core.domain.db_error_hook",
        }
    ),
)
