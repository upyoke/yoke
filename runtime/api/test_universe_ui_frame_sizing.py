"""The dashboard grows in document flow instead of a scrolling app frame."""

from __future__ import annotations

import re
from importlib.resources import files


def rule(css: str, selector: str) -> str:
    match = re.search(re.escape(selector) + r" \{(?P<body>[^}]*)\}", css)
    assert match is not None
    return re.sub(r"/\*.*?\*/", "", match.group("body"), flags=re.DOTALL)


def test_document_owns_dashboard_scrolling_and_short_pages_fill_the_viewport():
    chrome = files("yoke_core.ui").joinpath("static", "universe_chrome.css").read_text()
    for selector in [".local-universe-page", ".universe-app-root"]:
        declarations = rule(chrome, selector)
        assert "min-height: 100dvh;" in declarations
        assert re.search(r"(?:^|[;\s])height:", declarations) is None
        assert "overflow: hidden" not in declarations
    for selector in [
        ".universe-app-root .shell",
        ".universe-app-root .workbench-body",
        ".universe-app-root .content",
    ]:
        declarations = rule(chrome, selector)
        assert "overflow" not in declarations
        assert "height: 100%;" not in declarations
    assert "position: sticky;" in rule(chrome, ".universe-app-root .topbar")
    assert "top: 0;" in rule(chrome, ".universe-app-root .topbar")
    nav = rule(chrome, ".universe-app-root .shell > .sidenav")
    assert "position: sticky;" in nav
    assert "max-height: calc(100dvh - var(--yoke-app-header-height" in nav


def test_hosted_frame_harness_uses_document_flow_without_a_height_contract():
    harness = (
        files("yoke_core.ui")
        .joinpath("static", "hosted-frame-harness.html")
        .read_text()
    )
    assert '<div class="harness-host-container">' in harness
    assert "--yoke-app-frame-height" not in harness
    assert "height: var(--harness-bar-height);" in harness
    assert '"Create project"' not in harness


def test_phone_navigation_is_a_viewport_overlay_after_document_scroll():
    css = (
        files("yoke_core.ui").joinpath("static", "universe_responsive.css").read_text()
    )
    mobile = css[css.index("@media (max-width: 980px)") :]
    assert "position: fixed;" in rule(mobile, ".universe-app-root .shell > .sidenav")
    assert "max-height: 100dvh;" in rule(mobile, ".universe-app-root .shell > .sidenav")
    assert "position: fixed;" in rule(mobile, ".universe-app-root .navigation-scrim")
