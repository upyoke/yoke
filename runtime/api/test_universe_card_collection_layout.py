"""Shared workbench card grids size from content width, not the viewport."""

from __future__ import annotations

from importlib.resources import files


def _responsive() -> str:
    return (
        files("yoke_core.ui").joinpath("static", "universe_responsive.css").read_text()
    )


def test_shared_card_tracks_hold_still_whatever_a_section_holds():
    """Every section on a page draws the same columns at the same width.

    auto-fit collapses the tracks a section did not fill, so a one-card band
    stretched to the full width and a three-card band drew thirds while the
    band under it drew four columns. auto-fill keeps the empty tracks, which
    is what makes the count come from the available width alone.
    """
    responsive = _responsive()
    assert "repeat(auto-fill, minmax(" in responsive
    assert "repeat(auto-fit" not in responsive
    assert (
        "min(100%, var(--yoke-card-track-min)), var(--yoke-card-track-max)"
        in responsive
    )


def test_card_track_bounds_match_the_approved_prototype():
    """Bounds and gaps are the prototype's, per collection.

    Work, session and frontier cards are its .fr-grid/.sess-grid — 268px to
    360px at a 12px gap, so a short row stops rather than spanning a wide
    screen. Strategy documents are its .doc-row — 280px wide enough for a
    whole summary, taking the width it is given, at a 10px gap. Machines are
    its .mach-grid, 340px to 380px.
    """
    responsive = _responsive()
    shared = responsive.split(".universe-app-root {", 1)[1].split("}", 1)[0]
    assert "--yoke-card-track-min: 268px" in shared
    assert "--yoke-card-track-max: 360px" in shared
    assert "--yoke-card-grid-gap: 12px" in shared
    # Each collection names itself twice: once in the shared selector list and
    # once in its own override, which is the later of the two.
    docs = responsive.rsplit(".strategy-doc-grid {", 1)[1].split("}", 1)[0]
    assert "--yoke-card-track-min: 280px" in docs
    assert "--yoke-card-track-max: 1fr" in docs
    assert "--yoke-card-grid-gap: 10px" in docs
    machines = responsive.rsplit(".machines-grid {", 1)[1].split("}", 1)[0]
    assert "--yoke-card-track-min: 340px" in machines
    assert "--yoke-card-track-max: 380px" in machines


def test_the_overflow_tile_is_a_full_height_card_with_a_centred_label():
    """The See more tile keeps its row's height and centres its one word.

    It used to opt out of the row's stretch and align its label to the top,
    so it drew as a short box with the word sitting under the upper edge
    while every card beside it ran the full height of the row.
    """
    static = files("yoke_core.ui").joinpath("static")
    cards = static.joinpath("universe_work_cards.css").read_text()
    tile = cards.split(".see-more-card {", 1)[1].split("}", 1)[0]
    assert "align-items: center" in tile
    assert "justify-content: center" in tile
    assert "align-self" not in tile
    bands = static.joinpath("universe_bands.css").read_text()
    in_grid = bands.split("> .see-more-card {", 1)[1].split("}", 1)[0]
    assert "justify-content: center" in in_grid
    assert "align-self: start" not in in_grid


def test_writes_sits_a_section_away_from_the_band_above_it():
    """Archived is closed by default, so the gap cannot be its to give.

    The spacing is the writes host's own top margin and the same variable the
    bands space themselves with, so a collapsed or empty Archived band still
    leaves a section between the two.
    """
    static = files("yoke_core.ui").joinpath("static")
    chrome = static.joinpath("universe_chrome.css").read_text()
    assert "--yoke-band-gap: 22px" in chrome
    bands = static.joinpath("universe_bands.css").read_text()
    band = bands.split(".universe-app-root .work-band {", 1)[1].split("}", 1)[0]
    assert "margin-top: var(--yoke-band-gap)" in band
    strategy = static.joinpath("strategy.css").read_text()
    host = strategy.split(".strategy-writes-host {", 1)[1].split("}", 1)[0]
    assert "margin-top: var(--yoke-band-gap)" in host


def test_compact_widths_leave_the_card_grids_to_the_shared_rule():
    responsive = _responsive()
    compact = responsive.split("@media (max-width: 980px)", 1)[1]
    drawer = compact.split("@media (max-width: 640px)", 1)[0]
    assert ".session-grid" not in drawer
    assert ".work-card-grid" not in drawer
    assert ".machines-grid" not in drawer


def test_project_context_matches_the_shared_header_control_height():
    responsive = (
        files("yoke_core.ui").joinpath("static", "universe_responsive.css").read_text()
    )
    control = responsive.split(".header-context-control {", 1)[1].split("}", 1)[0]
    assert "height: 32px" in control
    assert "flex-wrap: nowrap" in control
    phone = responsive.split("@media (max-width: 640px)", 1)[1]
    assert "padding-bottom: 2px" not in phone
    host = responsive.split(".header-scope-host .scope-bar {", 1)[1].split("}", 1)[0]
    assert "overflow-x: auto" in host
    assert "flex-wrap: nowrap" in host
