"""What a Claude transcript row has to state, and how much of it is kept.

Claude stamps a ``message.usage`` block on every assistant row, and those
blocks are the whole of what the usage fold reads. The rest of a
transcript is content: a pasted file, a tool result, a compacted history,
any of which can pass a megabyte on its own. A row past the ordinary
record bound therefore keeps only the scalars below — the row's type, the
identity that deduplicates a turn written as several rows, the served
model, and the usage counts — and streams past everything else.

That distinction is the point. Before it, one oversized *user* row marked
a whole session's consumption partial, though it stated no usage at all
and nothing was lost with it. Now a projected row is a gap only when it
is an assistant row whose own usage statement did not survive.
"""

from __future__ import annotations

from typing import Any

from yoke_harness.artifact_record_projection import (
    RecordProjection,
    projection_decoder,
)
from yoke_harness.artifact_reader_version import replayed_for_reader, stamp_reader
from yoke_harness.artifact_watermark import ArtifactWatermark


#: Bumped when this reader recovers something the previous one lost, so
#: every record the previous one wrote is folded once more. The previous
#: reader held no projection at all: it skipped every row past the record
#: bound, whatever that row was.
_READER_VERSION = "projected-v1"
_READER_KEY = "claude_reader"

ASSISTANT_ROW_TYPE = "assistant"

_USAGE_KEYS = (
    "input_tokens cache_read_input_tokens cache_creation_input_tokens output_tokens"
).split()
_SELECTED_PATHS = frozenset(
    [
        ("type",),
        ("requestId",),
        ("message", "id"),
        ("message", "model"),
        ("message", "usage", "cache_creation", "ephemeral_5m_input_tokens"),
        ("message", "usage", "cache_creation", "ephemeral_1h_input_tokens"),
        ("message", "usage", "output_tokens_details", "thinking_tokens"),
    ]
    + [("message", "usage", key) for key in _USAGE_KEYS]
)


def _missing_relevant_projection(row: dict[str, Any]) -> bool:
    """True when an assistant row's consumption did not survive projection.

    Every other row type states no consumption, so losing one loses
    nothing this reader was reading for.
    """
    if row.get("type") != ASSISTANT_ROW_TYPE:
        return False
    message = row.get("message")
    if not isinstance(message, dict):
        return True
    if not isinstance(message.get("usage"), dict):
        return True
    if not str(message.get("model") or "").strip():
        return True
    return not (
        str(message.get("id") or "").strip() or str(row.get("requestId") or "").strip()
    )


CLAUDE_PROJECTION = RecordProjection(
    selected_paths=_SELECTED_PATHS,
    incomplete=_missing_relevant_projection,
)

claude_record_decoder = projection_decoder(CLAUDE_PROJECTION)


def prepare_claude_watermark(mark: ArtifactWatermark) -> ArtifactWatermark:
    """Resume a Claude fold, replaying once for records an older reader wrote.

    Claude totals accumulate per assistant message, so a replay starts
    from nothing: re-reading rows already summed into the stored totals
    would count every one of them twice. The dedup marker goes with them,
    because it names a row the replay is about to meet again.
    """
    return replayed_for_reader(
        mark,
        reader_key=_READER_KEY,
        reader_version=_READER_VERSION,
        additive=True,
    )


def stamp_claude_reader(totals: dict[str, Any]) -> dict[str, Any]:
    """Mark state as produced by the current selective decoder."""
    return stamp_reader(totals, reader_key=_READER_KEY, reader_version=_READER_VERSION)


__all__ = [
    "ASSISTANT_ROW_TYPE",
    "CLAUDE_PROJECTION",
    "claude_record_decoder",
    "prepare_claude_watermark",
    "stamp_claude_reader",
]
