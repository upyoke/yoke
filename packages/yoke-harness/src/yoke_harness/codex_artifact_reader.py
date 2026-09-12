"""What a Codex rollout record has to state, and how much of it is kept.

Codex writes two kinds of record this reader cares about: a
``turn_context`` naming the model a turn ran under, and a ``token_count``
event whose ``info.total_token_usage`` is the whole thread's cumulative
consumption. Both are small. Everything else in a rollout — the turns
themselves, and the compacted summaries that can reach tens of megabytes
— is content, so a record past the ordinary bound keeps only the scalars
below and forgets the rest as it streams.

A record projected that way is a gap only when it was one of the two this
reader needed and its statement did not survive: a ``turn_context``
without its model, or a ``token_count`` without its usage block. A giant
compacted record states neither and costs nothing to lose.
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
#: every record the previous one wrote is folded once more. The current
#: reader finishes a record wider than one scan budget rather than
#: abandoning it mid-record.
_READER_VERSION = "projected-v2"
_READER_KEY = "codex_reader"

USAGE_INCOMPLETE_KEY = "usage_incomplete"
MODEL_HISTORY_INCOMPLETE_KEY = "model_history_incomplete"

_PAYLOAD_KEYS = "type model effort model_context_window originator source".split()
_USAGE_KEYS = (
    "input_tokens cached_input_tokens cache_write_input_tokens "
    "output_tokens reasoning_output_tokens"
).split()
_SELECTED_PATHS = frozenset(
    [("type",), ("payload", "info", "model_context_window")]
    + [("payload", key) for key in _PAYLOAD_KEYS]
    + [("payload", "info", "total_token_usage", key) for key in _USAGE_KEYS]
)


def _missing_relevant_projection(row: dict[str, Any]) -> bool:
    payload = row.get("payload")
    if not isinstance(payload, dict):
        return False
    if row.get("type") == "turn_context":
        return not isinstance(payload.get("model"), str)
    if payload.get("type") != "token_count":
        return False
    info = payload.get("info")
    usage = info.get("total_token_usage") if isinstance(info, dict) else None
    return not isinstance(usage, dict)


CODEX_PROJECTION = RecordProjection(
    selected_paths=_SELECTED_PATHS,
    incomplete=_missing_relevant_projection,
)

codex_record_decoder = projection_decoder(CODEX_PROJECTION)


def prepare_codex_watermark(mark: ArtifactWatermark) -> ArtifactWatermark:
    """Resume a Codex fold, replaying once for records an older reader wrote.

    Codex totals are cumulative, so the replay keeps them: the newest
    statement replaces whatever is held. Only the two loss flags are
    cleared, because the fold about to run decides them again from bytes
    the current reader can read.
    """
    return replayed_for_reader(
        mark,
        reader_key=_READER_KEY,
        reader_version=_READER_VERSION,
        additive=False,
        cleared_keys=(USAGE_INCOMPLETE_KEY, MODEL_HISTORY_INCOMPLETE_KEY),
    )


def stamp_codex_reader(totals: dict[str, Any]) -> dict[str, Any]:
    """Mark state as produced by the current selective decoder."""
    return stamp_reader(totals, reader_key=_READER_KEY, reader_version=_READER_VERSION)


__all__ = [
    "CODEX_PROJECTION",
    "MODEL_HISTORY_INCOMPLETE_KEY",
    "USAGE_INCOMPLETE_KEY",
    "codex_record_decoder",
    "prepare_codex_watermark",
    "stamp_codex_reader",
]
