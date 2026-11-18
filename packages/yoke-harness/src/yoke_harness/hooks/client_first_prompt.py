"""Attest, from this session's own transcript, when its first prompt arrived.

The prompt hook is what normally records a session's first operator
prompt. When that hook never reaches the authority (a resident timeout, a
dropped relay), the session keeps no first-prompt stamp and reads as a
probe although a person talked to it. A terminal hook (Stop, SessionEnd)
can still prove the prompt happened: the harness wrote it to the
session's transcript. This collector reads that proof on the client,
where the transcript lives, and ships only the session id and the row's
native timestamp — never prompt text.

Which harnesses have a reader is declared per harness in
``yoke_contracts.harness_session_transcripts`` (``prompt_attestation``);
a ``deferred`` harness ships nothing.

The read is bounded: it scans from the start of the file, stops at the
first qualifying row, and gives up after :data:`MAX_ATTESTATION_SCAN_BYTES`.
Rows larger than the record bound are projected to the few scalars this
reader needs, so a giant pasted prompt is still recognised.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from yoke_contracts.executor_labels import canonical_harness_id
from yoke_contracts.harness_session_transcripts import session_transcripts_for_harness
from yoke_contracts.hook_runner.client_facts import FIRST_USER_PROMPT_KEY, client_fact
from yoke_contracts.timestamps import format_instant, parse_instant
from yoke_harness.artifact_record_projection import (
    RecordProjection,
    projection_decoder,
)
from yoke_harness.artifact_scan import iter_rows

#: Terminal hooks that may recover a lost first prompt.
ATTESTING_EVENTS = frozenset({"Stop", "SessionEnd"})

#: The most transcript bytes one attestation reads from the file start.
MAX_ATTESTATION_SCAN_BYTES = 8 << 20

#: Harness-written user rows that are output, not something a person typed.
_SYNTHETIC_PREFIXES = ("<local-command-stdout>", "<local-command-stderr>")

_PROMPT_BLOCK_TYPES = frozenset({"text", "image", "document"})

_PROJECTION = RecordProjection(
    selected_paths=frozenset(
        {
            ("type",),
            ("sessionId",),
            ("timestamp",),
            ("isMeta",),
            ("isSidechain",),
            ("isCompactSummary",),
            ("message", "role"),
            ("message", "content", "*", "type"),
        }
    ),
    # Only the scalars above decide; content is never needed whole.
    incomplete=lambda row: False,
)
_decoder = projection_decoder(_PROJECTION)


def is_operator_prompt(row: Mapping[str, Any], session_id: str) -> bool:
    """True when *row* is a prompt a person sent to exactly this session."""
    if row.get("type") != "user" or row.get("sessionId") != session_id:
        return False
    if row.get("isMeta") or row.get("isSidechain") or row.get("isCompactSummary"):
        return False
    message = row.get("message")
    if not isinstance(message, Mapping) or message.get("role") != "user":
        return False
    content = message.get("content")
    if isinstance(content, str):
        return bool(content.strip()) and not content.lstrip().startswith(
            _SYNTHETIC_PREFIXES
        )
    if isinstance(content, list):
        return any(
            isinstance(block, Mapping) and block.get("type") in _PROMPT_BLOCK_TYPES
            for block in content
        )
    if isinstance(content, Mapping):
        # A projected oversized row keeps only the last content block's type.
        block = content.get("*")
        return isinstance(block, Mapping) and block.get("type") in _PROMPT_BLOCK_TYPES
    # A projected oversized row whose content was one string: a typed prompt.
    return content is None and "content" not in message


def claude_first_prompt_at(transcript: Path, session_id: str) -> str | None:
    """The native timestamp of this session's first operator prompt, if any."""
    for row in iter_rows(
        transcript, max_bytes=MAX_ATTESTATION_SCAN_BYTES, record_factory=_decoder
    ):
        if is_operator_prompt(row, session_id):
            try:
                return format_instant(parse_instant(row.get("timestamp")))
            except (TypeError, ValueError):
                return None
    return None


def first_prompt_fact(obs) -> dict:
    """The first-prompt attestation for a terminal hook, or nothing."""
    if obs.event_name not in ATTESTING_EVENTS or obs.payload.get("isSidechain"):
        return {}
    try:
        harness = canonical_harness_id(obs.executor)
    except ValueError:
        return {}
    if session_transcripts_for_harness(harness).prompt_attestation != "claude_user_rows":
        return {}
    session_id = obs.payload.get("session_id")
    path = obs.payload.get("transcript_path")
    if not isinstance(session_id, str) or not session_id.strip():
        return {}
    if not isinstance(path, str) or not Path(path).is_file():
        return {}
    at = claude_first_prompt_at(Path(path), session_id)
    if at is None:
        return {}
    return client_fact(FIRST_USER_PROMPT_KEY, {"session_id": session_id, "at": at})


__all__ = [
    "ATTESTING_EVENTS",
    "MAX_ATTESTATION_SCAN_BYTES",
    "claude_first_prompt_at",
    "first_prompt_fact",
    "is_operator_prompt",
]
