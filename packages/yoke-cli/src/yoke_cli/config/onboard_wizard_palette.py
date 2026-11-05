"""Palette constants shared by the ``yoke setup`` wizard's Rich markup.

The full palette lives in ``onboard_wizard.tcss`` as ``$onboard-*`` variables for
the CSS-styled widgets. Rich console markup (used for per-word coloring like the
orange ``Yoke`` wordmark, the orange ``✓`` / red ``✗`` status glyphs, and the
stepper) cannot resolve TCSS ``$variables``, so the few hex values it needs are
mirrored here as one source of truth instead of being retyped per call site.
Keep these in sync with ``onboard_wizard.tcss``.
"""

from __future__ import annotations

# Steel orange accent ($onboard-accent / $onboard-brand) and missing/error red
# ($onboard-danger).
ACCENT = "#f4a261"
DANGER = "#f85149"

# Foreground text ($onboard-text) and the muted label tone ($onboard-dim),
# mirrored here for the few Rich-markup runs that color text per-word (e.g. the
# footer key glyphs vs. their labels).
TEXT = "#dfe6ec"
DIM = "#8995a1"

# The Yoke wordmark, brand-colored, ready to drop into a Rich-markup title.
BRAND = f"[{ACCENT}]Yoke[/]"

__all__ = ["ACCENT", "BRAND", "DANGER", "DIM", "TEXT"]
