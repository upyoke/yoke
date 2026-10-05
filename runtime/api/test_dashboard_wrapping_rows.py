"""Dashboard prose must never regain alignment that indents wrapped lines."""

from importlib.resources import files
import re

from yoke_core.ui.asset_roster import ASSET_CONTENT_TYPES


def test_trailing_alignment_is_reserved_for_non_wrapping_geometry():
    static = files("yoke_core.ui").joinpath("static")
    # The shell is a non-wrapping frame, usage-stat alignment is vertical,
    # and machine meters have fixed numeric columns and graphical tracks.
    permitted = {
        ("shell.css", ".yoke-app-header", "justify-content", "space-between"),
        ("shell.css", ".yoke-app-header .yoke-header-brand", "margin-right", "auto"),
        (
            "inbox.css",
            ".universe-app-root .inbox-sections .review-side",
            "justify-content",
            "space-between",
        ),
        (
            "universe_sessions_usage.css",
            ".universe-app-root .usage-stats",
            "align-items",
            "flex-end",
        ),
        (
            "universe_machines_panel.css",
            ".machine-capacity-track",
            "margin-left",
            "auto",
        ),
        (
            "universe_machines_panel.css",
            ".machine-limit-columns",
            "margin-left",
            "auto",
        ),
        (
            "universe_machines_panel.css",
            ".machine-limit-headroom, .machine-limit-quota",
            "text-align",
            "right",
        ),
    }
    found = set()
    for path in static.iterdir():
        if not path.name.endswith(".css"):
            continue
        source = re.sub(r"/\*.*?\*/", "", path.read_text(), flags=re.S)
        for selector, declarations in re.findall(r"([^{}]+)\{([^{}]*)\}", source):
            selector = " ".join(selector.split())
            for name, value in re.findall(r"([\w-]+)\s*:\s*([^;]+);", declarations):
                value = value.strip()
                if (name, value) in {
                    ("justify-content", "space-between"),
                    ("justify-content", "flex-end"),
                    ("align-items", "flex-end"),
                    ("margin-left", "auto"),
                    ("margin-right", "auto"),
                    ("text-align", "right"),
                }:
                    found.add((path.name, selector, name, value))
    assert found <= permitted, (
        f"Wrapped content can be indented by: {found - permitted}"
    )


def test_shared_wrapping_styles_are_served_through_every_dashboard_shell():
    static = files("yoke_core.ui").joinpath("static")
    assert ASSET_CONTENT_TYPES["wrapping_rows.css"] == "text/css; charset=utf-8"
    assert (
        '@import url("./wrapping_rows.css");' in static.joinpath("app.css").read_text()
    )


def test_numeric_meter_columns_cannot_wrap_their_right_aligned_values():
    source = (
        files("yoke_core.ui")
        .joinpath("static", "universe_machines_panel.css")
        .read_text()
    )
    numeric = source.split(".machine-limit-quota {", 1)[1].split("}", 1)[0]
    assert "white-space: nowrap" in numeric


def test_only_heading_copy_grows_in_wrapping_rows():
    source = files("yoke_core.ui").joinpath("static", "wrapping_rows.css").read_text()
    growing = [
        selector
        for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", source)
        if "flex-grow: 1" in body
    ]
    assert len(growing) == 2
    assert ":first-child" not in growing[0]
    assert ".activation-title" in growing[0]
    assert ".review-head-copy" in growing[0]
    assert ".panel-header > :is(h2, h3)" in growing[0]


def test_card_flow_style_does_not_share_the_item_panel_class():
    static = files("yoke_core.ui").joinpath("static")
    card = static.joinpath("universe_item_deployment.js").read_text()
    assert '"item-card-delivery-flow"' in card
    assert '"item-delivery-flow"' not in card
    assert (
        ".item-card-delivery-flow {"
        in static.joinpath("universe_item_signals.css").read_text()
    )
    assert ".item-delivery-flow {" in static.joinpath("item_details.css").read_text()


def test_workflow_mechanics_reserves_readable_copy_before_actions():
    source = files("yoke_core.ui").joinpath("static", "workflows.css").read_text()
    row = source.split(".workflow-detail-row {", 1)[1].split("}", 1)[0]
    copy = source.split(".workflow-detail-content {", 1)[1].split("}", 1)[0]
    assert "flex-wrap: wrap" in row
    assert "flex: 1 1 240px" in copy


def test_actor_inventory_wraps_unbroken_credential_identifiers():
    source = files("yoke_core.ui").joinpath("static", "universe_actors.css").read_text()
    key = source.split(".actors-key {", 1)[1].split("}", 1)[0]
    assert "overflow-wrap: anywhere" in key


def test_action_groups_have_no_auto_margin_after_wrapping():
    source = files("yoke_core.ui").joinpath("static", "wrapping_rows.css").read_text()
    assert "margin-inline-start: auto" not in source
    assert ".session-filter-actions" in source
    assert ".session-filter-search { max-width: none; }" in source


def test_mobile_header_keeps_intrinsic_widths_and_visible_actor_name():
    source = (
        files("yoke_core.ui").joinpath("static", "universe_responsive.css").read_text()
    )
    phone = source.split("@media (max-width: 640px)", 1)[1]
    assert "flex: 1 0 100%" not in phone
    assert ".actor-name { display: none" not in phone
    assert "height: 22px" in phone
    assert ".header-actor-context { order: 11; }" in phone


def test_session_control_geometry_uses_border_box_and_shared_icon():
    static = files("yoke_core.ui").joinpath("static")
    source = static.joinpath("universe_session_control.css").read_text()
    box = source.split(".session-roster-filter {", 1)[1].split("}", 1)[0]
    assert "box-sizing: border-box" in box
    assert "height: var(--session-control-height)" in box
    filters = static.joinpath("universe_session_roster_filters.js").read_text()
    assert 'magnifier(documentNode, "session-filter-search-icon")' in filters
