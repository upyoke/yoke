"""Claude `AdapterCapability` instance consumed by the shared hook runner.

The adapter is data-only: it names the events Claude subscribes to, points at
the existing JSON payload parser and the Claude-shaped decision renderer, and
declares no chain omissions. Claude includes `lint_write_path` on its
`apply_patch`-class chain (only Codex omits it), so
`apply_patch_chain_omissions` is empty.

The runner's `__main__` lazily imports this module for the detected harness;
no policy-evaluation code lives here.
"""

from __future__ import annotations

from runtime.harness.hook_runner.adapter_capability import AdapterCapability
from runtime.harness.hook_runner.decision_render import render_claude_decision
from runtime.harness.hook_runner.stdin import parse_json_payload

__all__ = ["CAPABILITY"]


CAPABILITY: AdapterCapability = AdapterCapability(
    family="claude",
    events=frozenset(
        {
            "SessionStart",
            "SessionEnd",
            "UserPromptSubmit",
            "PreToolUse",
            "PostToolUse",
            "Stop",
            "Notification",
            "SubagentStop",
            "PreCompact",
        }
    ),
    payload_parser=parse_json_payload,
    decision_renderer=render_claude_decision,
    apply_patch_chain_omissions=frozenset(),
    pretool_omissions=frozenset(),
    subprocess_modules=frozenset(
        {
            "yoke_core.domain.observe",
            "yoke_core.domain.db_error_hook",
        }
    ),
)
