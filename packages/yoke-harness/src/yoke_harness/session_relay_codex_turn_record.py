"""Read back whether one Codex session's turn is already over.

A Codex turn that ends on a vendor error fires no ``Stop`` hook, so
nothing tells the control plane that it finished. Its own rollout does:
the last line of
``~/.codex/sessions/YYYY/MM/DD/rollout-<started>-<session_id>.jsonl`` is a
``task_complete`` event once the turn ends, and that event carries an
``error`` payload when the turn ended on a vendor failure rather than on
an answer. The failing case observed live was
``{"message": "Selected model is at capacity", "codex_error_info":
"server_overloaded"}`` — the process stayed at its prompt, the session's
last hook event was the ``PostToolUse`` two seconds earlier, and the row
read as if it were still working.

Only the error-terminal end is reported. A clean ``task_complete`` belongs
to a session whose relay-run native exits on its own, and a tail that is
still a tool call belongs to a turn genuinely in flight; reclassifying
either would resume a session that does not need it.

Reading is deliberately shallow — one directory glob and one tail read,
no parse of the conversation — because it runs on a poll, against a store
that holds every session this machine has ever run.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping

from yoke_harness.hooks.identity_codex_runtime import codex_transcript_candidates


#: Enough of the tail to hold the terminal event, bounded so a rollout
#: carrying megabytes of captured tool output is never read whole.
_TAIL_BYTES = 1024 * 1024


@dataclass(frozen=True)
class ObservedTurnEnd:
    """One session's native record that its turn ended on an error."""

    session_id: str
    observed_at: str
    evidence: dict[str, Any]


def _rollout_path(session_id: str, roots: list[Path] | None) -> Path | None:
    """Return the newest rollout Codex wrote for this session, if any."""
    try:
        matches = codex_transcript_candidates(session_id, roots=roots)
    except OSError:
        return None
    return matches[0] if matches else None


def _tail_event(path: Path) -> Mapping[str, Any] | None:
    """Return the last complete JSON line, or ``None`` when there is none."""
    try:
        size = path.stat().st_size
        with open(path, "rb") as handle:
            if size > _TAIL_BYTES:
                handle.seek(size - _TAIL_BYTES)
                handle.readline()
            last = b""
            for raw in handle:
                stripped = raw.strip()
                if stripped:
                    last = stripped
    except OSError:
        return None
    if not last:
        return None
    try:
        event = json.loads(last)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return event if isinstance(event, Mapping) else None


def error_terminal_turn(
    session_id: str,
    *,
    transcript_roots: list[Path] | None = None,
) -> ObservedTurnEnd | None:
    """Return the turn end for a session whose last turn failed, else ``None``."""
    if not session_id:
        return None
    path = _rollout_path(session_id, transcript_roots)
    if path is None:
        return None
    event = _tail_event(path)
    if event is None:
        return None
    payload = event.get("payload")
    if not isinstance(payload, Mapping) or payload.get("type") != "task_complete":
        return None
    error = payload.get("error")
    if not isinstance(error, Mapping):
        return None
    return ObservedTurnEnd(
        session_id=session_id,
        observed_at=str(event.get("timestamp") or ""),
        evidence={
            "record": "codex_rollout_tail",
            "turn_id": str(payload.get("turn_id") or ""),
            # The vendor's own classification, which is the part an
            # operator asks for first when a fleet stalls at once.
            "codex_error_info": str(error.get("codex_error_info") or ""),
            "error_message": str(error.get("message") or ""),
        },
    )


__all__ = [
    "ObservedTurnEnd",
    "error_terminal_turn",
]
