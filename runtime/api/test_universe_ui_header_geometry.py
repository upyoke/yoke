"""The header is sized by what it holds, and it never runs off the side.

Between the drawer breakpoint and full desktop the header carries the
brand, the search field and three labelled contexts, and their total is
wider than the viewport at around 1024px. A fixed header track clipped
the overflow instead of showing it, so the actor control was simply cut
off the right edge — visible nowhere, reachable by nothing.

These pin the two rules that fix it: the header row sizes to the header,
and the header wraps rather than overflowing. Both are unconditional,
because the widths where this bites are the ordinary laptop ones, not a
phone.
"""

from importlib.resources import files


def _static(name: str) -> str:
    return files("yoke_core.ui").joinpath("static", name).read_text()


def test_the_header_row_is_as_tall_as_the_header():
    chrome = _static("universe_chrome.css")
    assert "grid-template-rows: auto minmax(0, 1fr);" in chrome
    assert "grid-template-rows: var(--yoke-header-height)" not in chrome


def test_the_header_wraps_instead_of_running_off_the_side():
    responsive = _static("universe_responsive.css")
    base = responsive.split("@media", 1)[0]
    assert ".universe-app-root .topbar {" in base
    topbar = base.split(".universe-app-root .topbar {", 1)[1].split("}", 1)[0]
    assert "flex-wrap: wrap" in topbar


def test_a_single_project_screen_separates_its_two_pickers():
    """Scope and focus are two chip rows in one control.

    Side by side they are wider than the header has room for from the
    drawer breakpoint down, and neither could shrink, so they took the
    header past the screen edge. The focus row takes its own line, the
    control grows to hold it instead of clipping at a fixed height, and
    its label stays visible — without it the second row is an unexplained
    copy of the first.

    The fix belongs at the drawer breakpoint, not at the phone one: 768px
    is where the header first runs out of room, and scoping it narrower
    left a tablet with the actor control off the screen.
    """
    responsive = _static("universe_responsive.css")
    compact = responsive.split("@media (max-width: 980px)", 1)[1]
    compact = compact.split("@media (max-width: 640px)", 1)[0]
    control = compact.split(".universe-app-root .header-project-context {", 1)[1]
    control = control.split("}", 1)[0]
    assert "height: auto" in control
    assert "flex-wrap: wrap" in control
    assert ".universe-app-root .header-scope-host .scope-bar .scope-bar {" in compact
    assert (
        ".universe-app-root .header-scope-host .scope-bar .scope-bar > .scope-label"
        in responsive
    )


# A control whose background, border or shadow changes with state, inside a
# container that clips, keeps a whole-pixel height. At a fractional height
# the repaint after the change can miss the partly covered bottom pixel row,
# and the old accent stays on screen as a thin line until a full repaint.
# These read the declared CSS, so they pin the arithmetic, not the render.


def _base(css: str) -> str:
    return css.split("@media", 1)[0]


def _breakpoint(css: str, query: str) -> str:
    return css.split(f"@media {query}", 1)[1].split("@media", 1)[0]


def _rule(css: str, selector: str) -> dict[str, str]:
    body = css.split(f"{selector} {{", 1)[1].split("}", 1)[0]
    declarations = {}
    for declaration in body.split(";"):
        name, _, value = declaration.partition(":")
        if value:
            declarations[name.strip()] = value.strip()
    return declarations


def _px(value: str) -> float:
    assert value == "0" or value.endswith("px"), value
    return float(value.removesuffix("px"))


def _vertical(*rules: dict[str, str]) -> float:
    """Vertical padding, top and bottom border, and px line-height or height.

    Later rules override earlier ones, as a state or breakpoint rule does.
    A border-box `height` is the whole box on its own.
    """
    top = bottom = border_top = border_bottom = line = 0.0
    fixed = None
    for rule in rules:
        if "padding" in rule:
            sides = [_px(part) for part in rule["padding"].split()]
            top, bottom = sides[0], sides[2] if len(sides) > 2 else sides[0]
        if "padding-block" in rule:
            top = bottom = _px(rule["padding-block"])
        if "border" in rule:
            border_top = border_bottom = _px(rule["border"].split()[0])
        if "border-bottom" in rule:
            border_bottom = _px(rule["border-bottom"].split()[0])
        if "line-height" in rule:
            line = _px(rule["line-height"])
        if "height" in rule:
            fixed = _px(rule["height"])
    if fixed is not None:
        return fixed
    return top + bottom + border_top + border_bottom + line


def _assert_whole(total: float) -> None:
    assert total == int(total), total


def test_header_scope_chips_are_whole_pixels_at_every_breakpoint():
    chrome = _base(_static("universe_chrome.css"))
    chip = _rule(chrome, ".universe-app-root .scope-chip")
    responsive = _static("universe_responsive.css")
    selector = ".universe-app-root .header-scope-host .scope-chip"
    header = _rule(_base(responsive), selector)
    assert header["line-height"] == "14px"
    assert _vertical(chip, header) == 20
    touch = _rule(_breakpoint(responsive, "(hover: none)"), selector)
    assert _vertical(chip, header, touch) == 22


def test_in_page_scope_chips_and_tabs_are_whole_pixels():
    chrome = _base(_static("universe_chrome.css"))
    assert _vertical(_rule(chrome, ".universe-app-root .scope-chip")) == 25
    tabs = _static("universe_tab_bar.css")
    assert _vertical(_rule(tabs, ".universe-app-root .tab-link")) == 34


def test_toggle_buttons_inside_panels_are_whole_pixels():
    activity = _base(_static("universe_secondary_activity.css"))
    assert _vertical(_rule(activity, ".universe-app-root .event-filter")) == 28
    performance = _static("universe_performance.css")
    buttons = ".performance-panel button, .performance-inspector button"
    assert _vertical(_rule(performance, buttons)) == 31


def test_selectable_cards_and_results_are_whole_pixels():
    workflows = _base(_static("workflows.css"))
    stage = _rule(workflows, ".universe-app-root .workflow-stage")
    selected = _rule(workflows, ".universe-app-root .workflow-stage.selected")
    _assert_whole(_vertical(stage))
    assert _vertical(stage) == _vertical(stage, selected)
    label = _rule(workflows, ".universe-app-root .workflow-stage-label")
    assert label["line-height"] == "17px"
    counts = (
        ".universe-app-root .workflow-stage-count,\n"
        ".universe-app-root .workflow-stage-detail-count"
    )
    assert _rule(workflows, counts)["line-height"] == "15px"

    posture = _base(_static("workflow_posture.css"))
    option = _rule(posture, ".universe-app-root .workflow-coordination-option")
    _assert_whole(_vertical(option))
    for part in ("name", "tag", "description"):
        rule = _rule(posture, f".universe-app-root .workflow-coordination-{part}")
        assert rule["line-height"].endswith("px")
        _assert_whole(_vertical(rule))

    search = _base(_static("universe_search.css"))
    _assert_whole(_vertical(_rule(search, ".universe-app-root .header-search-result")))
    label = _rule(search, ".universe-app-root .header-search-label")
    assert label["line-height"] == "18px"
    meta = (
        ".universe-app-root .header-search-meta,\n"
        ".universe-app-root .header-search-status"
    )
    assert _rule(search, meta)["line-height"] == "16px"


def test_a_selected_pending_machine_row_is_whole_pixels():
    """A collapsed border splits its pixel between two rows, so this table
    keeps separate borders, and every line in a row has a px height."""
    approval = _static("machine_approval.css")
    table = _rule(approval, ".universe-app-root .machine-pending table.items")
    assert table["border-collapse"] == "separate"
    for selector, line in (
        (".universe-app-root .machine-pending td", "19px"),
        (".universe-app-root .machine-pending td::before", "14px"),
        (".universe-app-root .machine-pending .pill", "16px"),
        (".universe-app-root .machine-pending .machine-approval-quiet", "17px"),
    ):
        assert _rule(approval, selector)["line-height"] == line
    content = _static("universe_content.css")
    cell = _rule(content, ".universe-app-root table.items td")
    assert _vertical(cell, {"line-height": "19px"}) == 40
