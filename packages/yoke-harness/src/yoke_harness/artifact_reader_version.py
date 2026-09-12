"""Fold an artifact again once, when a better reader replaces the old one.

A stored watermark carries the losses the reader that wrote it hit. Those
losses are remembered rather than recomputed, because the bytes they
happened in sit behind the offset — which is right until the reader
itself improves. A reader that can now read what its predecessor could
not has to re-read that artifact from the beginning exactly once, and the
reader version stamped into the stored totals is what makes it once
rather than every time.

How totals survive a replay is the reader's own semantics, and getting it
wrong is a double count rather than a gap. An additive accumulator sums
what it reads, so replaying it against totals that already hold those
rows would count them twice: it starts from nothing, dedup marker
included. A reader whose newest statement replaces the previous one keeps
its totals, and only the flags recording the loss are cleared so the
fresh fold can decide them again.
"""

from __future__ import annotations

from typing import Any

from yoke_harness.artifact_watermark import ArtifactWatermark, stored_totals


def replayed_for_reader(
    mark: ArtifactWatermark,
    *,
    reader_key: str,
    reader_version: str,
    additive: bool,
    cleared_keys: tuple[str, ...] = (),
) -> ArtifactWatermark:
    """Return the watermark this reader should resume from.

    Only a record carrying a loss is replayed: one that folded everything
    has nothing to recover, so its offset stays exactly where it is.
    """
    totals = dict(stored_totals(mark))
    if not mark.oversized or totals.get(reader_key) == reader_version:
        return mark
    if additive:
        return ArtifactWatermark(truncated=mark.truncated, caught_up=False)
    for key in cleared_keys:
        totals.pop(key, None)
    return ArtifactWatermark(
        last_key=mark.last_key,
        totals=totals,
        truncated=mark.truncated,
        caught_up=False,
    )


def stamp_reader(
    totals: dict[str, Any], *, reader_key: str, reader_version: str
) -> dict[str, Any]:
    """Record which reader produced these totals, for the replay above."""
    totals[reader_key] = reader_version
    return totals


__all__ = ["replayed_for_reader", "stamp_reader"]
