"""Bootstrap-orientation teaching tests for workflow item entry.

The compact and full ``main_agent`` blocks injected by
:mod:`yoke_core.domain.main_agent_packet` must surface the
workflow-selected, typed entry-surface rule so the top-level Yoke
session sees it when orientation renders.
"""

from __future__ import annotations

from pathlib import Path

from yoke_contracts.session_control.teaching import (
    FLEET_BODY_TRUST_GUIDANCE,
    FLEET_ENVELOPE_TRUST_GUIDANCE,
    FLEET_TOP_LEVEL_RECEIPT_GUIDANCE,
)
from yoke_core.domain.main_agent_packet import (
    render_main_agent_block,
    render_main_agent_block_full,
)
from yoke_core.domain.session_orientation import render_orientation
from yoke_core.hooks.session_dispatch import (
    _render_claude_orientation,
    _render_codex_orientation,
)


_ENTRY_TOKENS = ("Work-item entry surfaces", "/yoke idea", "harness_skill")
_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_main_agent_compact_block_includes_item_entry_rule() -> None:
    block = render_main_agent_block()
    assert block, "compact main_agent block rendered empty"
    for token in _ENTRY_TOKENS:
        assert token in block, f"compact main_agent block missing token {token!r}"


def test_main_agent_full_block_includes_item_entry_rule() -> None:
    block = render_main_agent_block_full()
    assert block, "full main_agent block rendered empty"
    for token in _ENTRY_TOKENS:
        assert token in block, f"full main_agent block missing token {token!r}"


def test_main_agent_bootstrap_distinguishes_receipt_from_body_authority() -> None:
    for block in (render_main_agent_block(), render_main_agent_block_full()):
        assert FLEET_ENVELOPE_TRUST_GUIDANCE in block
        assert FLEET_BODY_TRUST_GUIDANCE in block
        assert FLEET_TOP_LEVEL_RECEIPT_GUIDANCE in block


def test_every_top_level_harness_context_carries_receipt_trust_boundary() -> None:
    contexts = {
        "claude": _render_claude_orientation(
            "claude-session", str(_REPO_ROOT), "", "claude-code", "claude-model"
        ),
        "codex": _render_codex_orientation(
            "codex-session", str(_REPO_ROOT), "", "codex-model", "codex-desktop"
        ),
        "cursor": render_orientation({"session_id": "cursor-session"}, _REPO_ROOT),
    }
    for surface, context in contexts.items():
        assert FLEET_ENVELOPE_TRUST_GUIDANCE in context, surface
        assert FLEET_BODY_TRUST_GUIDANCE in context, surface
        assert FLEET_TOP_LEVEL_RECEIPT_GUIDANCE in context, surface
