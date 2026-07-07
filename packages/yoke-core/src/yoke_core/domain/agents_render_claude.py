"""Claude harness substrate rendering — settings.json, manifest.json.

Renders Claude-side substrate from universal Yoke source:

- ``runtime/harness/claude/settings.json`` — hooks block (universal ordering)
  plus Claude-specific permissions block.
- ``runtime/harness/claude/manifest.json`` — Yoke-shaped harness manifest.

The Claude agent ``.md`` adapter tree is owned by the existing
``yoke_core.domain.agents_render`` orchestrator (preserved unchanged).
"""

from __future__ import annotations

import json

from yoke_core.domain.agents_render_hooks import render_claude_hooks_block
from yoke_core.domain.agents_render_manifests import CLAUDE_MANIFEST


# Claude permissions — operator-authored static block reproduced here so the
# rendered settings.json includes it. Permissions are not derived from
# universal source; they are Claude-specific tool gates that mirror the
# harness's permission contract.
CLAUDE_PERMISSIONS: dict = {
    "allow": [
        "Bash",
        "Write(**)",
        "Edit(**)",
        "Read(*)",
        "Grep(*)",
        "Glob(*)",
        "Monitor",
    ]
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
        # Yoke policy: project context (CLAUDE.md, AGENTS.md, session rules,
        # skill prose, ticket bodies) is the only durable surface. Claude's
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
