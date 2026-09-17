"""The content sections an item detail read will serve, named once.

The engine validates the names and the CLI offers them, so the roster lives
where both sides already depend: one tuple, no second spelling to drift.
"""

from __future__ import annotations

#: Content sections ``items.detail.get`` serves in full when named. Anything
#: outside this tuple is refused by name rather than ignored.
DETAIL_INCLUDE_SECTIONS = ("narrative", "body", "progress_log")

#: The sections whose text is item content, and therefore the ones whose
#: delivery carries the operator's execution instructions with it. This is
#: the rule ``items.get.run`` already applies to its own ``body`` projection:
#: authority travels with the content it governs, and a read that delivers no
#: content carries no instruction bodies.
CONTENT_BEARING_SECTIONS = ("narrative", "body")

#: What ``yoke items detail get`` serves without being asked: the spec a
#: reader came for, and the operator authority that travels with it. The body
#: renders the same fields again and the Progress Log is its own read, so both
#: wait in the content index until named.
DEFAULT_DETAIL_SECTIONS = ("narrative",)


__all__ = [
    "CONTENT_BEARING_SECTIONS",
    "DEFAULT_DETAIL_SECTIONS",
    "DETAIL_INCLUDE_SECTIONS",
]
