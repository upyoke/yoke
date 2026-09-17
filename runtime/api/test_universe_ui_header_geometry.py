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
