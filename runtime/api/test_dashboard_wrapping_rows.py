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
