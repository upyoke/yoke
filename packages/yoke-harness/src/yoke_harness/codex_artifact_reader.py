"""Decode ordinary Codex JSON and project oversized records."""

from __future__ import annotations

import codecs
import json
from dataclasses import dataclass
from typing import Any, Optional

from yoke_harness.artifact_scan import parse_row
from yoke_harness.artifact_watermark import ArtifactWatermark, stored_totals

_READER_MARKER = "projected-v1"
_READER_MARKER_KEY = "codex_reader"
_MAX_SCALAR_BYTES = 4_096
_UNKNOWN_KEY = "\0"
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


@dataclass
class _Container:
    kind: str
    path: tuple[str, ...]
    state: str
    key: Optional[str] = None


class CodexRecordDecoder:
    """Decode ordinary rows in C; project only rows beyond the normal bound."""

    def __init__(self, record_limit: int) -> None:
        self._record_limit = record_limit
        self._buffer = bytearray()
        self._projecting = False
        self._stack: list[_Container] = []
        self._root_state = "value"
        self._root_object = False
        self._row: dict[str, Any] = {}
        self._invalid = False
        self._string_role = ""
        self._string_path: tuple[str, ...] = ()
        self._string_bytes = bytearray()
        self._string_capture = False
        self._selected_overflow = False
        self._escaped = False
        self._unicode_digits = 0
        self._utf8 = codecs.getincrementaldecoder("utf-8")()
        self._bare_path: tuple[str, ...] = ()
        self._bare_bytes = bytearray()
        self._in_bare = False
        self.record_bytes = 0
        self.peak_retained_bytes = 0
        self.unrecoverable = False
        self.full_decodes = 0

    def feed(self, data: bytes | memoryview) -> None:
        self.record_bytes += len(data)
        if not self._projecting:
            room = self._record_limit + 1 - len(self._buffer)
            self._buffer.extend(data[:room])
            self.peak_retained_bytes = max(self.peak_retained_bytes, len(self._buffer))
            if len(self._buffer) <= self._record_limit:
                return
            prefix = bytes(self._buffer)
            self._buffer.clear()
            self._projecting = True
            for byte in prefix:
                self._accept(byte)
            data = data[room:]
        if self._invalid:
            return
        for byte in data:
            self._accept(byte)

    def finish(self) -> Optional[dict[str, Any]]:
        if not self._projecting:
            self.full_decodes = 1
            return parse_row(bytes(self._buffer))
        if self._in_bare:
            self._finish_bare()
        valid = (
            not self._invalid
            and not self._string_role
            and not self._stack
            and self._root_state == "done"
            and self._root_object
        )
        self.unrecoverable = self.record_bytes > self._record_limit and (
            not valid
            or self._selected_overflow
            or (valid and _missing_relevant_projection(self._row))
        )
        return self._row if valid else None

    def _accept(self, byte: int) -> None:
        if self._string_role:
            self._accept_string(byte)
            return
        if self._in_bare:
            if byte in b" \t\r,]}":
                self._finish_bare()
                if self._invalid:
                    return
            else:
                self._append_bare(byte)
                return
        if byte in b" \t\r":
            return
        if not self._stack:
            if self._root_state == "done":
                self._invalid = True
                return
            self._start_value(byte, ())
            return
        parent = self._stack[-1]
        if parent.kind == "object":
            self._accept_object(parent, byte)
        else:
            self._accept_array(parent, byte)

    def _accept_object(self, parent: _Container, byte: int) -> None:
        if parent.state in {"key_or_end", "key"}:
            if byte == ord("}") and parent.state == "key_or_end":
                self._close_container()
            elif byte == ord('"'):
                self._start_string("key", ())
            else:
                self._invalid = True
            return
        if parent.state == "colon":
            if byte == ord(":"):
                parent.state = "value"
            else:
                self._invalid = True
            return
        if parent.state == "value":
            self._start_value(byte, parent.path + (parent.key or _UNKNOWN_KEY,))
            return
        if byte == ord(","):
            parent.state = "key"
        elif byte == ord("}"):
            self._close_container()
        else:
            self._invalid = True

    def _accept_array(self, parent: _Container, byte: int) -> None:
        if parent.state in {"value_or_end", "value"}:
            if byte == ord("]") and parent.state == "value_or_end":
                self._close_container()
            else:
                self._start_value(byte, parent.path + ("*",))
            return
        if byte == ord(","):
            parent.state = "value"
        elif byte == ord("]"):
            self._close_container()
        else:
            self._invalid = True

    def _start_value(self, byte: int, path: tuple[str, ...]) -> None:
        if byte == ord("{"):
            if not self._stack and self._root_state == "value":
                self._root_object = True
            self._stack.append(_Container("object", path, "key_or_end"))
        elif byte == ord("["):
            self._stack.append(_Container("array", path, "value_or_end"))
        elif byte == ord('"'):
            self._start_string("value", path)
        elif byte in b"-0123456789tfn":
            self._in_bare = True
            self._bare_path = path
            self._bare_bytes.clear()
            self._append_bare(byte)
        else:
            self._invalid = True

    def _start_string(self, role: str, path: tuple[str, ...]) -> None:
        self._string_role = role
        self._string_path = path
        self._string_capture = role == "key" or path in _SELECTED_PATHS
        self._string_bytes.clear()
        self._escaped = False
        self._unicode_digits = 0
        self._utf8 = codecs.getincrementaldecoder("utf-8")()

    def _accept_string(self, byte: int) -> None:
        if self._unicode_digits:
            if byte not in b"0123456789abcdefABCDEF":
                self._invalid = True
                return
            self._unicode_digits -= 1
            self._append_string(byte)
            return
        if self._escaped:
            if byte not in b'"\\/bfnrtu':
                self._invalid = True
                return
            self._escaped = False
            self._unicode_digits = 4 if byte == ord("u") else 0
            self._append_string(byte)
            return
        if byte == ord("\\"):
            self._escaped = True
            self._append_string(byte)
            return
        if byte == ord('"'):
            self._finish_string()
            return
        if byte < 0x20:
            self._invalid = True
            return
        self._append_string(byte)

    def _append_string(self, byte: int) -> None:
        try:
            self._utf8.decode(bytes((byte,)), final=False)
        except UnicodeDecodeError:
            self._invalid = True
            return
        if self._string_capture:
            if len(self._string_bytes) < _MAX_SCALAR_BYTES:
                self._string_bytes.append(byte)
                self._track_peak()
            else:
                self._string_capture = False
                if self._string_role == "value":
                    self._selected_overflow = True

    def _finish_string(self) -> None:
        try:
            self._utf8.decode(b"", final=True)
        except UnicodeDecodeError:
            self._invalid = True
            return
        role = self._string_role
        path = self._string_path
        value: Optional[str] = None
        if self._string_capture:
            try:
                decoded = json.loads(b'"' + bytes(self._string_bytes) + b'"')
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
                self._invalid = True
                return
            value = decoded if isinstance(decoded, str) else None
        self._string_role = ""
        if role == "key":
            parent = self._stack[-1]
            parent.key = value or _UNKNOWN_KEY
            parent.state = "colon"
        else:
            if value is not None and path in _SELECTED_PATHS:
                _assign(self._row, path, value)
            self._complete_value()

    def _append_bare(self, byte: int) -> None:
        if len(self._bare_bytes) >= 128:
            self._invalid = True
            return
        self._bare_bytes.append(byte)
        self._track_peak()

    def _finish_bare(self) -> None:
        try:
            value = json.loads(bytes(self._bare_bytes))
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            self._invalid = True
            return
        path = self._bare_path
        self._in_bare = False
        self._bare_bytes.clear()
        if path in _SELECTED_PATHS:
            _assign(self._row, path, value)
        self._complete_value()

    def _close_container(self) -> None:
        self._stack.pop()
        self._complete_value()

    def _complete_value(self) -> None:
        if self._stack:
            parent = self._stack[-1]
            parent.state = "comma_or_end"
            parent.key = None
        else:
            self._root_state = "done"

    def _track_peak(self) -> None:
        retained = len(self._string_bytes) + len(self._bare_bytes)
        self.peak_retained_bytes = max(self.peak_retained_bytes, retained)


def codex_record_decoder(record_limit: int) -> CodexRecordDecoder:
    return CodexRecordDecoder(record_limit)


def prepare_codex_watermark(mark: ArtifactWatermark) -> ArtifactWatermark:
    """Restart a bounded fold once for records saved by the old decoder."""
    totals = dict(stored_totals(mark))
    if mark.oversized and totals.get(_READER_MARKER_KEY) != _READER_MARKER:
        return ArtifactWatermark(
            offset=0,
            last_key=mark.last_key,
            totals=totals,
            truncated=mark.truncated,
            caught_up=False,
        )
    return mark


def stamp_codex_reader(totals: dict[str, Any]) -> dict[str, Any]:
    """Mark state as produced by the selective decoder."""
    totals[_READER_MARKER_KEY] = _READER_MARKER
    return totals


def _assign(document: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    target = document
    for key in path[:-1]:
        child = target.get(key)
        if not isinstance(child, dict):
            child = {}
            target[key] = child
        target = child
    target[path[-1]] = value


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
