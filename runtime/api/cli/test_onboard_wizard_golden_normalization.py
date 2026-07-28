"""Determinism checks for the Textual SVG golden normalizer."""

import asyncio

from runtime.api.cli.onboard_wizard_golden_support import (
    _normalize,
    _stable_screenshot,
)


def test_normalize_prunes_only_unreferenced_terminal_styles() -> None:
    svg = """<svg>
<style>
.terminal-123-r1 { fill: #ffffff }
.terminal-123-r2 { fill: #000000 }
</style>
<text class="terminal-123-r1">visible</text>
</svg>
"""

    normalized = _normalize(svg)

    assert ".terminal-YOKE-r1 { fill: #ffffff }" in normalized
    assert ".terminal-YOKE-r2" not in normalized
    assert 'class="terminal-YOKE-r1"' in normalized


def test_normalize_prunes_invisible_text_without_hiding_visible_glyphs() -> None:
    svg = """<svg>
<style>
.terminal-123-r1 { fill: #000000 }
.terminal-123-r2 { fill: #3fb950 }
</style>
<text class="terminal-123-r1" x="10">&#160;\n  </text>
<text class="terminal-123-r2" x="20">█</text>
</svg>
"""

    normalized = _normalize(svg)

    assert ".terminal-YOKE-r1" not in normalized
    assert 'class="terminal-YOKE-r1"' not in normalized
    assert ".terminal-YOKE-r2 { fill: #3fb950 }" in normalized
    assert '<text class="terminal-YOKE-r2" x="20">█</text>' in normalized


def test_stable_screenshot_drains_scheduled_ui_work_before_comparing() -> None:
    class App:
        settled = False

        def export_screenshot(self, *, title: str) -> str:
            state = "settled" if self.settled else "intermediate"
            return f"{title}:{state}"

    app = App()

    class Pilot:
        scheduled_waits = 0

        async def wait_for_scheduled_animations(self) -> None:
            self.scheduled_waits += 1
            app.settled = True

        async def pause(self) -> None:
            return None

    pilot = Pilot()

    captured = asyncio.run(_stable_screenshot(pilot, app, "preview"))

    assert captured == "preview:settled"
    assert pilot.scheduled_waits == 1
