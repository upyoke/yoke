"""Read a growing harness artifact once, no matter how often it is read.

Usage and served-model facts land on the control plane by riding hook
events, and hook events are frequent, so re-parsing a transcript that has
grown to tens of megabytes on every tool call is not affordable. Each
session therefore keeps a small machine-local record of how far into its
artifact it has already folded, and each read resumes from exactly there.
The ``kind`` names which reader's progress a record holds, so the usage
fold and the model-fact fold advance independently over the same file.

That record is also what makes repeated observation safe. The offset
advances only after the bytes before it are folded into the stored
totals, so a read that crashes mid-fold re-reads rather than skips, and a
read that finds nothing new returns what it already had. The totals sent
upward are always absolute, never deltas, so even a duplicated send
cannot double-count: the control plane replaces rather than adds.

Two hooks firing at once are the case a resume offset alone cannot
survive. A record written in place is momentarily absent, and a reader
that met it then would replay the whole history against a watermark that
already existed; two folds racing can also leave the older offset written
last, unreading content already counted. So a record is replaced
atomically, and the whole load-read-fold-save span is held under one
per-artifact lock: whoever holds it folds, and whoever does not reuses the
totals already persisted rather than duplicating the read.

A shrinking file is the one case that cannot be resumed. A truncated or
rotated artifact no longer contains the history the stored totals were
built from, so the record resets to the beginning and the reading it
produces is marked partial: what is left is real, and what is gone is
gone.
"""

from __future__ import annotations

import fcntl
import json
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Optional

from yoke_cli.config import machine_config
from yoke_harness.artifact_scan import OVERSIZED_RECORD_REASON


#: Progress of the token-consumption fold.
USAGE_KIND = "usage"
#: Progress of the served model/effort/window fold.
MODEL_KIND = "model"

_PRUNE_AGE_S = 7 * 86400

#: Recorded when a shrinking artifact forces a reread from the beginning.
TRUNCATED_ARTIFACT_REASON = (
    "harness artifact was truncated or rotated, so consumption recorded "
    "before that point is no longer readable"
)


@dataclass
class ArtifactWatermark:
    """How far one session's artifact has been folded, and into what.

    ``totals`` is the accumulator each reader keeps in its own shape; this
    module neither interprets nor validates it. ``last_key`` is the dedup
    marker a reader uses to recognize a record it has already counted
    across a resume boundary — the case a byte offset alone cannot cover,
    because one logical record can span the boundary as several physical
    rows. ``oversized`` remembers that a record was skipped for exceeding
    the reader's record bound, because what it stated stays uncounted for
    the rest of the session.
    """

    offset: int = 0
    last_key: str = ""
    totals: dict[str, Any] = field(default_factory=dict)
    truncated: bool = False
    oversized: bool = False


def watermark_path(session_id: str, *, kind: str = USAGE_KIND) -> Path:
    return machine_config.yoke_home() / f"session-{kind}" / f"{session_id}.json"


@contextmanager
def watermark_lock(
    session_id: str, *, kind: str = USAGE_KIND, blocking: bool = False
) -> Iterator[bool]:
    """Yield whether this caller may fold ``session_id``'s artifact now.

    The lock is held per session and reader kind on a file beside the
    record itself, so it excludes resident-server threads and separate
    fallback hook processes alike. ``blocking`` is for a caller whose
    input exists only in this invocation — a Cursor hook payload states
    its turn once, so yielding the fold would lose it — while a caller
    folding a file that is still there next time takes the record it
    finds instead of waiting behind the reader already doing the work.
    """
    if not session_id:
        yield True
        return
    target = watermark_path(session_id, kind=kind)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(
            target.parent / f"{target.name}.lock", os.O_RDWR | os.O_CREAT, 0o600
        )
    except OSError:
        yield True
        return
    acquired = False
    try:
        try:
            fcntl.flock(
                descriptor,
                fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB,
            )
            acquired = True
        except (BlockingIOError, OSError):
            acquired = False
        yield acquired
    finally:
        if acquired:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def load_watermark(
    session_id: str, artifact: Path, *, kind: str = USAGE_KIND
) -> ArtifactWatermark:
    """Return where reading should resume for ``artifact``.

    A record naming a different artifact than the one being read is not
    this file's watermark — a session whose transcript moved starts over
    against the new one rather than resuming at an offset that means
    nothing there.
    """
    if not session_id:
        return ArtifactWatermark()
    try:
        stored = json.loads(
            watermark_path(session_id, kind=kind).read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return ArtifactWatermark()
    if not isinstance(stored, dict):
        return ArtifactWatermark()
    if str(stored.get("artifact") or "") != str(artifact):
        return ArtifactWatermark()
    mark = ArtifactWatermark(
        offset=_non_negative(stored.get("offset")),
        last_key=str(stored.get("last_key") or ""),
        totals=stored.get("totals") if isinstance(stored.get("totals"), dict) else {},
        truncated=bool(stored.get("truncated")),
        oversized=bool(stored.get("oversized")),
    )
    return _reset_if_shrunk(mark, artifact)


def save_watermark(
    session_id: str,
    artifact: Path,
    mark: ArtifactWatermark,
    *,
    kind: str = USAGE_KIND,
) -> None:
    """Replace ``mark`` atomically, best effort — a failed write costs a reread.

    The replacement is what a concurrent reader depends on: a record
    written in place is briefly empty or half-written, and a reader
    meeting it then would read no watermark at all and replay the whole
    artifact from byte zero.
    """
    if not session_id:
        return
    target = watermark_path(session_id, kind=kind)
    staged = target.parent / f"{target.name}.{os.getpid()}.staged"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        staged.write_text(
            json.dumps(
                {
                    "artifact": str(artifact),
                    "offset": mark.offset,
                    "last_key": mark.last_key,
                    "totals": mark.totals,
                    "truncated": mark.truncated,
                    "oversized": mark.oversized,
                }
            ),
            encoding="utf-8",
        )
        os.replace(staged, target)
        _prune(target.parent)
    except OSError:
        _discard(staged)


def _discard(staged: Path) -> None:
    try:
        staged.unlink()
    except OSError:
        return


def _reset_if_shrunk(mark: ArtifactWatermark, artifact: Path) -> ArtifactWatermark:
    try:
        size = artifact.stat().st_size
    except OSError:
        return mark
    if size >= mark.offset:
        return mark
    return ArtifactWatermark(truncated=True)


def _non_negative(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


def _prune(directory: Path) -> None:
    """Drop records for sessions that stopped writing a week ago.

    Only the records themselves: a lock file is created once and never
    written again, so an old one can still belong to a session folding
    right now, and removing it would leave two folds excluding nothing.
    """
    cutoff = time.time() - _PRUNE_AGE_S
    try:
        entries = list(directory.iterdir())
    except OSError:
        return
    for entry in entries:
        if entry.suffix != ".json":
            continue
        try:
            if entry.stat().st_mtime < cutoff:
                entry.unlink()
        except OSError:
            continue


def stored_totals(mark: ArtifactWatermark) -> dict[str, Any]:
    return mark.totals if isinstance(mark.totals, dict) else {}


def partial_reason(mark: ArtifactWatermark) -> Optional[str]:
    """Why a reading built on ``mark`` is less than the whole session."""
    if mark.truncated:
        return TRUNCATED_ARTIFACT_REASON
    if mark.oversized:
        return OVERSIZED_RECORD_REASON
    return None


__all__ = [
    "MODEL_KIND",
    "TRUNCATED_ARTIFACT_REASON",
    "USAGE_KIND",
    "ArtifactWatermark",
    "load_watermark",
    "partial_reason",
    "save_watermark",
    "stored_totals",
    "watermark_lock",
    "watermark_path",
]
