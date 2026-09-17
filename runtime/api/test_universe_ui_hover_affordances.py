"""Hover is reserved for what can actually be clicked.

A hover response promises an action, so a container that lifts, tints or
underlines under the pointer and does nothing when clicked is a defect —
and it is the defect that comes back the moment somebody styles the card
instead of the link inside it.
"""

from importlib.resources import files


def test_hover_is_reserved_for_what_can_actually_be_clicked():
    """A hover response promises an action.

    Each of these dressed something the product never made clickable: a
    session card that carries its own controls and is not an anchor, the
    requirement row beside a plan link, the wrapper around an evidence
    strip, and a delivery member rendered as a span when it has no page.
    A card that lifts under the pointer and does nothing when clicked is
    the defect this guards.
    """
    static_root = files("yoke_core.ui").joinpath("static")
    for sheet, selector in (
        ("universe_sessions.css", ".session-card:hover"),
        ("item_details.css", ".item-proof-row:hover"),
        ("universe_work_cards.css", ".shipping-run-evidence:hover"),
        ("universe_work_cards.css", ".work-item-card:hover"),
    ):
        text = static_root.joinpath(sheet).read_text()
        assert selector not in text, f"{sheet} still styles {selector}"
    members = static_root.joinpath("universe_secondary_activity.css").read_text()
    assert "a.delivery-member:hover" in members
    assert "\n.universe-app-root .delivery-member:hover" not in members
