"""Bounded latest-main-agent final-response facts for the Stop turn gate.

Returns only ``available`` / ``present`` / ``question``. Never dumps a
transcript. Claude, Codex, and Cursor JSONL shapes normalize through this
one contract; a payload that already carries the same facts wins.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


PAYLOAD_KEY = "turn_end_evidence"
MAX_TRANSCRIPT_TAIL_BYTES = 262144

_USER_TYPES = frozenset({"user", "human"})
_SUBAGENT_MARKERS = frozenset({
    "parent_conversation_id",
    "parent_tool_use_id",
    "isSidechain",
    "is_subagent",
    "subagent_id",
})
_TEXT_PART_TYPES = frozenset({"text", "output_text", "input_text"})


@dataclass(frozen=True)
class TurnEndEvidence:
    """Latest main-agent final-text facts the Stop gate is allowed to see."""

    available: bool
    present: bool
    question: bool

    def as_dict(self) -> dict[str, bool]:
        return {
            "available": self.available,
            "present": self.present,
            "question": self.question,
        }


UNAVAILABLE = TurnEndEvidence(available=False, present=False, question=False)


def _looks_like_question(text: str) -> bool:
    """True when any stripped line ends with ``?``, not only the whole text."""
    return any(line.strip().endswith("?") for line in text.splitlines())


def _as_mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def from_payload_facts(payload: Mapping[str, Any]) -> TurnEndEvidence | None:
    """Return already-normalized facts, or a single final-response field."""
    raw = payload.get(PAYLOAD_KEY)
    if isinstance(raw, Mapping) and "available" in raw:
        available = bool(raw.get("available"))
        present = bool(raw.get("present"))
        question = bool(raw.get("question"))
        if not available:
            return UNAVAILABLE
        return TurnEndEvidence(available=True, present=present, question=question)
    for key in ("final_response", "last_assistant_text", "last_message"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            text = value.strip()
            return TurnEndEvidence(
                available=True,
                present=True,
                question=_looks_like_question(text),
            )
    return None


def _part_text(part: Any) -> str:
    if isinstance(part, str):
        return part
    mapping = _as_mapping(part)
    if mapping is None:
        return ""
    kind = mapping.get("type")
    if kind is not None and kind not in _TEXT_PART_TYPES:
        return ""
    text = mapping.get("text")
    return text if isinstance(text, str) else ""


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(_part_text(part) for part in content)
    mapping = _as_mapping(content)
    if mapping is None:
        return ""
    return _content_text(mapping.get("text") or mapping.get("content") or "")


def _looks_subagent(record: Mapping[str, Any], nested: Mapping[str, Any]) -> bool:
    for key in _SUBAGENT_MARKERS:
        if record.get(key) or nested.get(key):
            return True
    return False


def _assistant_text(record: Mapping[str, Any]) -> str | None:
    """Return main-agent assistant text, or None when the line is not one."""
    payload = _as_mapping(record.get("payload")) or {}
    message = _as_mapping(record.get("message")) or _as_mapping(payload.get("message")) or {}
    role = str(
        record.get("role") or message.get("role") or payload.get("role") or ""
    ).lower()
    kind = str(
        record.get("type") or payload.get("type") or record.get("record_type") or ""
    ).lower()
    if role in _USER_TYPES or kind in _USER_TYPES:
        return None
    if _looks_subagent(record, {**payload, **message}):
        return None
    assistant_like = (
        role == "assistant"
        or kind in {"assistant", "agent_message", "response_item"}
        or payload.get("type") == "agent_message"
    )
    if not assistant_like:
        return None
    text = _content_text(
        message.get("content")
        or payload.get("content")
        or record.get("content")
        or payload.get("message")
        or record.get("text")
    )
    stripped = text.strip()
    return stripped or None


def extract_from_jsonl(text: str) -> TurnEndEvidence:
    """Scan JSONL; the last main-agent assistant text is the only fact."""
    last: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        mapping = _as_mapping(parsed)
        if mapping is None:
            continue
        candidate = _assistant_text(mapping)
        if candidate is not None:
            last = candidate
    if last is None:
        return UNAVAILABLE
    return TurnEndEvidence(
        available=True,
        present=True,
        question=_looks_like_question(last),
    )


def read_transcript_tail(path: str) -> str | None:
    """Read at most ``MAX_TRANSCRIPT_TAIL_BYTES`` from the end of *path*."""
    try:
        target = Path(path)
        size = target.stat().st_size
        with target.open("rb") as handle:
            if size > MAX_TRANSCRIPT_TAIL_BYTES:
                handle.seek(-MAX_TRANSCRIPT_TAIL_BYTES, 2)
            data = handle.read(MAX_TRANSCRIPT_TAIL_BYTES)
    except OSError:
        return None
    return data.decode("utf-8", errors="replace")


def extract_turn_end_evidence(
    *,
    payload: Mapping[str, Any],
    transcript_text: str | None = None,
) -> TurnEndEvidence:
    """Normalize payload facts, else the supplied JSONL tail."""
    from_payload = from_payload_facts(payload)
    if from_payload is not None:
        return from_payload
    if transcript_text is None:
        return UNAVAILABLE
    return extract_from_jsonl(transcript_text)


__all__ = [
    "MAX_TRANSCRIPT_TAIL_BYTES",
    "PAYLOAD_KEY",
    "TurnEndEvidence",
    "UNAVAILABLE",
    "extract_from_jsonl",
    "extract_turn_end_evidence",
    "from_payload_facts",
    "read_transcript_tail",
]
