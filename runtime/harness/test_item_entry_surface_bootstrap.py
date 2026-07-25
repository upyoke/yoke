"""Bootstrap-orientation teaching tests for workflow item entry.

The compact and full ``main_agent`` blocks injected by
:mod:`yoke_core.domain.main_agent_packet` must surface the
workflow-selected, typed entry-surface rule so the top-level Yoke
session sees it when orientation renders.
"""

from __future__ import annotations

from yoke_core.domain.main_agent_packet import (
    render_main_agent_block,
    render_main_agent_block_full,
)


_ENTRY_TOKENS = ("Work-item entry surfaces", "/yoke idea", "harness_skill")


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
