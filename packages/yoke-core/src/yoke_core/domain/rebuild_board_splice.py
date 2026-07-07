"""Compatibility re-export for the shared generated-board splice helpers.

The splice logic is pure text composition and ships in ``yoke_contracts`` so a
client can write its ``BOARD.md`` without loading ``yoke_core``. These names
are re-exported here for the source-dev tier's existing importers.
"""

from yoke_contracts.board.splice import (  # noqa: F401
    CONFLICT_PREFIXES,
    MARKER_END,
    MARKER_START,
    _fresh_board_text,
    _marker_line,
    _strip_conflict_markers,
    _strip_generated_prefix_padding,
    splice_board,
)

__all__ = ["_fresh_board_text", "splice_board"]
