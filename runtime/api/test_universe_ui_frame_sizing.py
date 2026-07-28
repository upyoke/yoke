"""The app frame's height contract with the page or host that mounts it."""

from __future__ import annotations

import re
from importlib.resources import files


def test_app_frame_sizes_itself_rather_than_reading_a_host_height():
    """The frame stands the full window on its own so its footer anchors to
    the bottom of it. Reading the height off an ancestor makes every host
    re-derive the rule, and a host wrapper that declares only min-height
    leaves the percentage indefinite: the frame collapses to content height,
    the footer rides up under short pages, and long ones scroll the host
    document instead of the content pane. A host insets the frame with the
    custom property, which is why the declaration keeps a fallback."""
    chrome = files("yoke_core.ui").joinpath("static", "universe_chrome.css").read_text()
    root_rule = re.search(
        r"\.universe-app-root \{(?P<body>[^}]*)\}",
        chrome,
        re.DOTALL,
    )
    assert root_rule is not None
    declarations = re.sub(r"/\*.*?\*/", "", root_rule.group("body"), flags=re.DOTALL)
    assert "height: var(--yoke-app-frame-height, 100dvh);" in declarations
    assert "height: 100%;" not in declarations


def test_hosted_frame_harness_mounts_through_an_unsized_host_container():
    """The harness proves the hosted frame only if its mount root sits where
    a host's does: inside a plain wrapper carrying no definite height of its
    own. The wrapper declares the inset the harness bar costs instead, the
    way a host declares one, so both halves of the sizing contract are
    exercised on a laptop rather than in the hosted product."""
    harness = (
        files("yoke_core.ui")
        .joinpath("static", "hosted-frame-harness.html")
        .read_text()
    )
    assert '<div class="harness-host-container">' in harness
    container = re.search(
        r"\.harness-host-container \{(?P<body>[^}]*)\}",
        harness,
        re.DOTALL,
    )
    assert container is not None
    body = container.group("body")
    # No height of its own, not even a min: any sizing here would hide exactly
    # the collapse this container exists to expose.
    assert re.search(r"(?:^|[;{\s])(?:min-)?height:", body) is None
    # The inset names the bar's one height rather than restating its pixels.
    assert "--yoke-app-frame-height: calc(100dvh - var(--harness-bar-height));" in body
    assert "height: var(--harness-bar-height);" in harness
