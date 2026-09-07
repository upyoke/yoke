"""Read a growing harness artifact once, no matter how often it is read.

Usage lands on the control plane by riding hook events, and hook events
are frequent, so re-parsing a transcript that has grown to tens of
megabytes on every tool call is not affordable. Each session therefore
keeps a small machine-local record of how far into its artifact it has
already folded, and each read resumes from exactly there.

That record is also what makes repeated observation safe. The offset
advances only after the bytes before it are folded into the stored
totals, so a read that crashes mid-fold re-reads rather than skips, and a
read that finds nothing new returns what it already had. The totals sent
upward are always absolute, never deltas, so even a duplicated send
cannot double-count: the control plane replaces rather than adds.

A shrinking file is the one case that cannot be resumed. A truncated or
rotated artifact no longer contains the history the stored totals were
built from, so the record resets to the beginning and the reading it
produces is marked partial: what is left is real, and what is gone is
gone.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from yoke_cli.config import machine_config


_USAGE_DIR_NAME = "session-usage"
_PRUNE_AGE_S = 7 * 86400

#: Recorded when a shrinking artifact forces a reread from the beginning.
TRUNCATED_ARTIFACT_REASON = (
    "harness artifact was truncated or rotated, so consumption recorded "
    "before that point is no longer readable"
)


@dataclass
class UsageWatermark:
    """How far one session's artifact has been folded, and into what.

    ``totals`` is the accumulator each harness reader keeps in its own
    shape; this module neither interprets nor validates it. ``last_key``
    is the dedup marker a reader uses to recognize a record it has already
    counted across a resume boundary — the case a byte offset alone cannot
    cover, because one logical record can span the boundary as several
    physical rows.
    """

    offset: int = 0
    last_key: str = ""
    totals: dict[str, Any] = field(default_factory=dict)
    truncated: bool = False


def watermark_path(session_id: str) -> Path:
    return machine_config.yoke_home() / _USAGE_DIR_NAME / f"{session_id}.json"


def load_watermark(session_id: str, artifact: Path) -> UsageWatermark:
    """Return where reading should resume for ``artifact``.

    A record naming a different artifact than the one being read is not
    this file's watermark — a session whose transcript moved starts over
    against the new one rather than resuming at an offset that means
    nothing there.
    """
    if not session_id:
        return UsageWatermark()
    try:
        stored = json.loads(watermark_path(session_id).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return UsageWatermark()
    if not isinstance(stored, dict):
        return UsageWatermark()
    if str(stored.get("artifact") or "") != str(artifact):
        return UsageWatermark()
    mark = UsageWatermark(
        offset=_non_negative(stored.get("offset")),
        last_key=str(stored.get("last_key") or ""),
        totals=stored.get("totals") if isinstance(stored.get("totals"), dict) else {},
        truncated=bool(stored.get("truncated")),
    )
    return _reset_if_shrunk(mark, artifact)


def save_watermark(session_id: str, artifact: Path, mark: UsageWatermark) -> None:
    """Persist ``mark``, best effort — a failed write only costs a reread."""
    if not session_id:
        return
    try:
        target = watermark_path(session_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(
                {
                    "artifact": str(artifact),
                    "offset": mark.offset,
                    "last_key": mark.last_key,
                    "totals": mark.totals,
                    "truncated": mark.truncated,
                }
            ),
            encoding="utf-8",
        )
        _prune(target.parent)
    except OSError:
        return


def read_new_lines(artifact: Path, mark: UsageWatermark) -> tuple[list[str], int]:
    """Return the complete lines after ``mark.offset`` and the new offset.

    A trailing partial line is left unread: a harness appending a record
    while this runs would otherwise be parsed as truncated JSON and
    dropped, and the next read picks it up whole.
    """
    try:
        with artifact.open("rb") as handle:
            handle.seek(mark.offset)
            chunk = handle.read()
    except OSError:
        return [], mark.offset
    if not chunk:
        return [], mark.offset
    complete, _, remainder = chunk.rpartition(b"\n")
    if not complete and not remainder.endswith(b"\n"):
        return [], mark.offset
    text = complete.decode("utf-8", errors="replace")
    return [line for line in text.splitlines() if line.strip()], mark.offset + len(
        complete
    ) + 1


def _reset_if_shrunk(mark: UsageWatermark, artifact: Path) -> UsageWatermark:
    try:
        size = artifact.stat().st_size
    except OSError:
        return mark
    if size >= mark.offset:
        return mark
    return UsageWatermark(truncated=True)


def _non_negative(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


def _prune(directory: Path) -> None:
    """Drop records for sessions that stopped writing a week ago."""
    cutoff = time.time() - _PRUNE_AGE_S
    try:
        entries = list(directory.iterdir())
    except OSError:
        return
    for entry in entries:
        try:
            if entry.stat().st_mtime < cutoff:
                entry.unlink()
        except OSError:
            continue


def resolve_json_rows(lines: list[str]) -> list[dict]:
    """Parse each line as a JSON object, dropping anything else."""
    rows: list[dict] = []
    for line in lines:
        try:
            parsed = json.loads(line)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        if isinstance(parsed, dict):
            rows.append(parsed)
    return rows


def stored_totals(mark: UsageWatermark) -> dict[str, Any]:
    return mark.totals if isinstance(mark.totals, dict) else {}


def truncation_reason(mark: UsageWatermark) -> Optional[str]:
    """The partial-reading reason a reset watermark carries, if any."""
    return TRUNCATED_ARTIFACT_REASON if mark.truncated else None


__all__ = [
    "TRUNCATED_ARTIFACT_REASON",
    "UsageWatermark",
    "load_watermark",
    "read_new_lines",
    "resolve_json_rows",
    "save_watermark",
    "stored_totals",
    "truncation_reason",
    "watermark_path",
]
