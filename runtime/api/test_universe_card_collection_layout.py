"""Shared workbench card grids size from content width, not the viewport."""

from __future__ import annotations

from importlib.resources import files


def test_shared_card_tracks_use_content_width_and_readable_bounds():
    """Cards fill the row they are in; only the minimum is declared.

    The minimum decides how many fit, and it differs by what the card has to
    hold. Capping the track instead left a strip of empty page beside three
    cards, which is why the maximum is gone rather than raised.
    """
    responsive = (
        files("yoke_core.ui").joinpath("static", "universe_responsive.css").read_text()
    )
    assert "--yoke-card-track-min: 300px" in responsive
    assert "--yoke-card-track-min: 280px" in responsive
    assert "--yoke-card-track-min: 440px" in responsive
    assert "yoke-card-track-max" not in responsive
    assert "minmax(min(100%, var(--yoke-card-track-min)), 1fr)" in responsive
    assert "auto-fill" in responsive
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
