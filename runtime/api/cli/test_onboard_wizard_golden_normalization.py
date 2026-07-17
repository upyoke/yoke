"""Determinism checks for the Textual SVG golden normalizer."""

from runtime.api.cli.onboard_wizard_golden_support import _normalize


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
