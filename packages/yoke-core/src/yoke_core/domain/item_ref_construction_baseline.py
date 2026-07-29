"""Grandfathered ref-prefix-literal counts, keyed by repo-relative POSIX path.

``HC-item-ref-construction`` is a ratchet: any literal item-ref prefix in a file
that is *not* listed here, or *more* occurrences than listed, fails the check.
Legacy occurrences that have not yet been converted to the canonical formatter
live here so the gate can land without a flag-day rewrite.

This map may only SHRINK. Convert a site to ``render_item_ref`` /
``format_item_ref`` (display) or ``resolve_item_id`` (resolution), then lower or
delete its entry. When the map is empty the anti-pattern is fully gone and the
check is a pure zero-tolerance gate.
"""

from __future__ import annotations

# Populated from the live residual after the conversion sweep. Empty means
# zero tolerance.
BASELINE: dict[str, int] = {}
