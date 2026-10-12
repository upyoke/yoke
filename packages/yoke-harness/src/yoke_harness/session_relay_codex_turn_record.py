"""Read back whether one Codex session's turn is already over.

A Codex turn that ends on a vendor error fires no ``Stop`` hook, so
nothing tells the control plane that it finished. Its own rollout does:
the newest terminal event in
``~/.codex/sessions/YYYY/MM/DD/rollout-<started>-<session_id>.jsonl`` contains a
``task_complete`` event once the turn ends, and that event carries an
``error`` payload when the turn ended on a vendor failure rather than on
an answer. The failing case observed live was
``{"message": "Selected model is at capacity", "codex_error_info":
"server_overloaded"}`` — the process stayed at its prompt, the session's
last hook event was the ``PostToolUse`` two seconds earlier, and the row
read as if it were still working.

Both clean and failed ``task_complete`` events prove the turn ended. A clean
ending can leave posture running when project authorization denied its Stop
hook. A later prompt or tool call invalidates either terminal observation.

Reading is deliberately shallow — one directory glob and one tail read,
no parse of the conversation — because it runs on a poll, against a store
that holds every session this machine has ever run.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Any, Mapping

from yoke_contracts.timestamps import InvalidInstant, parse_instant
from yoke_harness.hooks.identity_codex_runtime import codex_transcript_candidates


#: Enough of the tail to hold the terminal event, bounded so a rollout
#: carrying megabytes of captured tool output is never read whole.
_TAIL_BYTES = 1024 * 1024


@dataclass(frozen=True)
class ObservedTurnEnd:
    """One session's native record that its turn ended."""

    session_id: str
    observed_at: datetime
    evidence: dict[str, Any]


def _rollout_path(session_id: str, roots: list[Path] | None) -> Path | None:
    """Return the newest rollout Codex wrote for this session, if any."""
    try:
        matches = codex_transcript_candidates(session_id, roots=roots)
    except OSError:
        return None
    return matches[0] if matches else None


def _tail_event(path: Path) -> Mapping[str, Any] | None:
    """Newest terminal event, allowing only tool settlement records after it.

    Codex can kill a command after ending the turn and append item_completed.
    A new prompt, tool call, or malformed record makes that end stale instead.
    """
    try:
        size = path.stat().st_size
        with open(path, "rb") as handle:
            if size > _TAIL_BYTES:
                handle.seek(size - _TAIL_BYTES)
                handle.readline()
            terminal = None
            for raw in handle:
                if not raw.strip():
                    continue
                try:
                    event = json.loads(raw)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    terminal = None
                    continue
                payload = event.get("payload") if isinstance(event, Mapping) else None
                kind = payload.get("type") if isinstance(payload, Mapping) else None
                if kind == "task_complete":
                    terminal = event
                elif not (
                    kind == "item_completed"
                    and terminal is not None
                    and payload.get("turn_id") == terminal["payload"].get("turn_id")
                ):
                    terminal = None
    except OSError:
        return None
    return terminal


def session_record_written_at(
    session_id: str,
    *,
    transcript_roots: list[Path] | None = None,
) -> float | None:
    """When Codex last wrote this session's rollout, if it keeps one.

    Codex appends every reasoning item to the rollout as it streams, so a
    growing rollout proves a turn is alive even when no tool call has fired a
    hook. ``None`` means no rollout exists for the id, which proves nothing.
    """
    if not session_id:
        return None
    path = _rollout_path(session_id, transcript_roots)
    if path is None:
        return None
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def terminal_turn(
    session_id: str,
    *,
    transcript_roots: list[Path] | None = None,
) -> ObservedTurnEnd | None:
    """Return the newest completed turn, clean or failed, else ``None``."""
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
    error = error if isinstance(error, Mapping) else {}
    try:
        observed_at = parse_instant(event.get("timestamp"))
    except InvalidInstant:
        # An unreadable clock cannot order this end against a newer turn.
        return None
    return ObservedTurnEnd(
        session_id=session_id,
        observed_at=observed_at,
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
    "session_record_written_at",
    "terminal_turn",
]
