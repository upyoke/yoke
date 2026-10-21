"""Column-listing regressions for the schema cheat-sheet packet."""

from __future__ import annotations

from yoke_core.domain import schema_api_context as sac
from yoke_core.domain.schema_api_context_render import PACKET_DETAIL_FULL


def test_harness_sessions_column_line_lists_offered_at() -> None:
    """The real session checkpoint timestamp is listed as a column."""
    body = sac.render_topic_packet("claims", detail=PACKET_DETAIL_FULL)
    column_line = next(
        line for line in body.splitlines() if "**`harness_sessions`**" in line
    )
    assert "offered_at" in column_line
