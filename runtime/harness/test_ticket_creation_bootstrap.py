"""Bootstrap-orientation teaching tests for idea-only ticket intake.

The compact and full ``main_agent`` blocks injected by
:mod:`runtime.harness.bootstrap_packets` must surface the
``/yoke idea`` ticket-intake rule so the top-level Yoke session
sees it the moment orientation renders, before any lower-level item /
body / claim / REST recipe shows up.
"""

from __future__ import annotations

from runtime.harness.bootstrap_packets import (
    render_main_agent_block,
    render_main_agent_block_full,
)


_IDEA_TOKENS = ("Ticket intake", "/yoke idea")


def test_main_agent_compact_block_includes_ticket_intake_rule() -> None:
    block = render_main_agent_block()
    assert block, "compact main_agent block rendered empty"
    for token in _IDEA_TOKENS:
        assert token in block, f"compact main_agent block missing token {token!r}"


def test_main_agent_full_block_includes_ticket_intake_rule() -> None:
    block = render_main_agent_block_full()
    assert block, "full main_agent block rendered empty"
    for token in _IDEA_TOKENS:
        assert token in block, f"full main_agent block missing token {token!r}"
