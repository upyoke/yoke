"""Function-inventory coverage for workflow item entry.

Item creation flows through ``/yoke idea``; no retained terminal boundary
may advertise a lower-level create surface.
"""

from __future__ import annotations

from yoke_core.domain.function_inventory_data import RETAINED_TERMINAL_BOUNDARIES


def test_item_creation_is_not_a_retained_boundary() -> None:
    """Item creation must not be classified as agent-facing retained."""
    forbidden_categories = {"agent_terminal", "retained_terminal_create"}
    for boundary in RETAINED_TERMINAL_BOUNDARIES:
        surface_lc = boundary.surface.lower()
        # No retained boundary should advertise item creation as a sanctioned
        # terminal recipe. (Creation flows through `/yoke idea`.)
        assert "items add" not in surface_lc, (
            f"retained boundary {boundary.surface!r} names `items add` — "
            "creation belongs to /yoke idea, not a retained terminal"
        )
        assert "backlog-cli add" not in surface_lc, (
            f"retained boundary {boundary.surface!r} names `backlog-cli add` — "
            "creation belongs to /yoke idea, not a retained terminal"
        )
        assert "post /v1/items" not in surface_lc, (
            f"retained boundary {boundary.surface!r} names `POST /v1/items` — "
            "creation belongs to /yoke idea, not a retained terminal"
        )
        assert boundary.category not in forbidden_categories
