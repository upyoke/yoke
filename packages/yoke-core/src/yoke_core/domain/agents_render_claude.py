"""Claude harness substrate rendering — settings.json, manifest.json.

Renders Claude-side substrate from universal Yoke source:

- ``runtime/harness/claude/settings.json`` — hooks block (universal ordering)
  plus Claude-specific permissions and status line blocks.
- ``runtime/harness/claude/manifest.json`` — Yoke-shaped harness manifest.

The Claude agent ``.md`` adapter tree is owned by the existing
``yoke_core.domain.agents_render`` orchestrator (preserved unchanged).
"""

from __future__ import annotations

import json

from yoke_core.domain.agents_render_hooks import render_claude_hooks_block
from yoke_core.domain.agents_render_manifests import CLAUDE_MANIFEST
from yoke_harness.hooks.shell_command import hook_shell_command


# Claude permissions — operator-authored static block reproduced here so the
# rendered settings.json includes it. Permissions are not derived from
# universal source; they are Claude-specific tool gates that mirror the
# harness's permission contract.
#
# File-editing access is Edit(**) only. Claude's file-permission matcher
# ignores Write(**) and warns that Edit rules cover every file-editing tool.
# Sibling allow entries stay as-is: Bash and Monitor are tool-level gates,
# and Read(*) / Grep(*) / Glob(*) are those tools' own path forms.
CLAUDE_PERMISSIONS: dict = {
    "allow": [
        "Bash",
        "Edit(**)",
        "Read(*)",
        "Grep(*)",
        "Glob(*)",
        "Monitor",
    ]
}


# Claude states the context window it is serving in exactly one
# machine-readable place: the JSON it pipes to the status line command.
# Hook payloads and transcript rows carry usage and never the window, so
# without this entry a Claude session's served context_window_tokens can
# only stay NULL — a requested [1m] tier would go forever unverified.
# Claude allows one status line per session and hides most footer keyboard
# hints once any is configured, so the command earns the slot by printing
# the model, window and usage; an operator who wants their own sets
# `statusLine` in .claude/settings.local.json, which overrides this and
# gives up the attestation with it.
CLAUDE_STATUS_LINE: dict = {
    "type": "command",
    "command": hook_shell_command("yoke hook status-line"),
}


def render_claude_settings_json() -> str:
    """Render Claude ``settings.json`` content with leading ``_generated`` marker.

    JSON has no comment syntax; emit a top-level ``_generated`` field
    instead. Claude tolerates unknown top-level keys and the field is the
    operator-visible "do not hand-edit" gate.
    """
    payload = {
        "_generated": (
            "by yoke_core.domain.agents_render — do not hand-edit. "
            "Source: yoke_contracts.hook_runner.hook_ordering + "
            "yoke_core.domain.agents_render_hooks."
        ),
        "hooks": render_claude_hooks_block(),
        "permissions": CLAUDE_PERMISSIONS,
        "statusLine": CLAUDE_STATUS_LINE,
        # Yoke policy: project context (CLAUDE.md, AGENTS.md, session rules,
        # skill prose, work-item bodies) is the only durable surface. Claude's
        # auto-memory subsystem would route rules into a per-machine file that
        # only loads when the model checks it, obscuring drift between what
        # the operator sees and what every agent inherits.
        "autoMemoryEnabled": False,
    }
    return json.dumps(payload, indent=2, sort_keys=False, ensure_ascii=False) + "\n"


def render_claude_manifest_json() -> str:
    """Render Claude ``manifest.json`` content with leading ``_generated`` marker."""
    payload = {
        "_generated": (
            "by yoke_core.domain.agents_render — do not hand-edit. "
            "Source: yoke_core.domain.agents_render_manifests.CLAUDE_MANIFEST."
        ),
        **CLAUDE_MANIFEST,
    }
    return json.dumps(payload, indent=2, sort_keys=False, ensure_ascii=False) + "\n"
