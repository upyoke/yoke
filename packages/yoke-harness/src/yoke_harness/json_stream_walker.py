"""Walk JSON bytes as they arrive, reporting only the scalars asked for.

A record too large to hold in memory can still be read, as long as reading
it never means holding it. This walker consumes a byte stream, tracks the
key path it is currently inside, and hands its owner each scalar sitting
at a path that owner selected. Everything else — the compacted turn, the
pasted file, the base64 image — passes through and is forgotten.

Two properties make that safe rather than merely cheap. The walk validates
structure as it goes, so a caller learns whether it saw one complete JSON
object rather than assuming it did; and a selected scalar longer than
:data:`MAX_SCALAR_BYTES` is reported as an overflow instead of being
truncated into a plausible-looking wrong value.

Speed is part of correctness here, because this runs on a hook event, so
the bytes inside an unselected string are skipped in one bulk step per
escape — the difference between milliseconds and seconds on a record of
tens of megabytes.
"""

from __future__ import annotations

import codecs
import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Optional


#: The longest single scalar a walk reports. A value longer than this is
#: content that happens to sit at a selected path rather than a fact, and
#: keeping it would restore the memory cost the walk exists to avoid.
MAX_SCALAR_BYTES = 4_096

#: Structural key of a member whose own key could not be read.
UNKNOWN_KEY = "\0"

#: The bytes that end a bulk skip through an unselected string: its close
#: quote, an escape, and the control bytes JSON forbids unescaped.
_STRING_STOP = re.compile(rb'[\x00-\x1f"\\]')

_BARE_VALUE_LIMIT = 128


@dataclass
class _Container:
    kind: str
    path: tuple[str, ...]
    state: str
    key: Optional[str] = None


class JsonStreamWalker:
    """Read one JSON value from a byte stream, keeping selected scalars.

    ``select`` decides, from a path, whether a scalar is worth reporting;
    ``emit`` receives the ones that are. Array members appear in a path
    as ``"*"``.
    """

    def __init__(
        self,
        *,
        select: Callable[[tuple[str, ...]], bool],
        emit: Callable[[tuple[str, ...], Any], None],
    ) -> None:
        self._select = select
        self._emit = emit
        self._stack: list[_Container] = []
        self._root_state = "value"
        self._root_object = False
        self._string_role = ""
        self._string_path: tuple[str, ...] = ()
        self._string_bytes = bytearray()
        self._string_capture = False
        self._escaped = False
        self._unicode_digits = 0
        self._utf8 = codecs.getincrementaldecoder("utf-8")()
        self._bare_path: tuple[str, ...] = ()
        self._bare_bytes = bytearray()
        self._in_bare = False
        self.invalid = False
        self.overflowed = False
        self.peak_retained_bytes = 0

    @property
    def complete(self) -> bool:
        """True when exactly one whole JSON object has been walked."""
        return (
            not self.invalid
            and not self._string_role
            and not self._stack
            and self._root_state == "done"
            and self._root_object
        )

    def feed(self, data: bytes) -> None:
        """Walk one span, skipping unselected string content in bulk.

        Most of an oversized record is one or two strings nobody
        selected, and walking those byte by byte in Python is what would
        make reading such a record cost seconds on a hook event.
        """
        index = 0
        size = len(data)
        while index < size:
            if self._skippable_string():
                stop = self._skip_string(data, index, size)
                if self.invalid:
                    return
                if stop > index:
                    index = stop
                    continue
                # The byte at ``index`` is the escape or the close quote
                # that ended the skip, so it is walked rather than
                # skipped — returning here without consuming it would
                # search the same byte forever.
            self._accept(data[index])
            if self.invalid:
                return
            index += 1

    def finish(self) -> None:
        """Close a bare value the stream ended on, with no delimiter."""
        if self._in_bare:
            self._finish_bare()

    def _skippable_string(self) -> bool:
        return bool(
            self._string_role
            and not self._string_capture
            and not self._escaped
            and not self._unicode_digits
        )

    def _skip_string(self, data: bytes, index: int, size: int) -> int:
        """Return where the skip stopped: an escape, a quote, or the end."""
        match = _STRING_STOP.search(data, index)
        stop = match.start() if match else size
        try:
            self._utf8.decode(data[index:stop], final=False)
        except UnicodeDecodeError:
            self.invalid = True
        return stop

    def _accept(self, byte: int) -> None:
        if self._string_role:
            self._accept_string(byte)
            return
        if self._in_bare:
            if byte in b" \t\r,]}":
                self._finish_bare()
                if self.invalid:
                    return
            else:
                self._append_bare(byte)
                return
        if byte in b" \t\r":
            return
        if not self._stack:
            if self._root_state == "done":
                self.invalid = True
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
                self.invalid = True
            return
        if parent.state == "colon":
            if byte == ord(":"):
                parent.state = "value"
            else:
                self.invalid = True
            return
        if parent.state == "value":
            self._start_value(byte, parent.path + (parent.key or UNKNOWN_KEY,))
            return
        if byte == ord(","):
            parent.state = "key"
        elif byte == ord("}"):
            self._close_container()
        else:
            self.invalid = True

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
            self.invalid = True

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
            self.invalid = True

    def _start_string(self, role: str, path: tuple[str, ...]) -> None:
        self._string_role = role
        self._string_path = path
        self._string_capture = role == "key" or self._select(path)
        self._string_bytes.clear()
        self._escaped = False
        self._unicode_digits = 0
        self._utf8 = codecs.getincrementaldecoder("utf-8")()

    def _accept_string(self, byte: int) -> None:
        if self._unicode_digits:
            if byte not in b"0123456789abcdefABCDEF":
                self.invalid = True
                return
            self._unicode_digits -= 1
            self._append_string(byte)
            return
        if self._escaped:
            if byte not in b'"\\/bfnrtu':
                self.invalid = True
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
            self.invalid = True
            return
        self._append_string(byte)

    def _append_string(self, byte: int) -> None:
        try:
            self._utf8.decode(bytes((byte,)), final=False)
        except UnicodeDecodeError:
            self.invalid = True
            return
        if not self._string_capture:
            return
        if len(self._string_bytes) < MAX_SCALAR_BYTES:
            self._string_bytes.append(byte)
            self._track_peak()
            return
        self._string_capture = False
        if self._string_role == "value":
            self.overflowed = True

    def _finish_string(self) -> None:
        try:
            self._utf8.decode(b"", final=True)
        except UnicodeDecodeError:
            self.invalid = True
            return
        role = self._string_role
        path = self._string_path
        value: Optional[str] = None
        if self._string_capture:
            try:
                decoded = json.loads(b'"' + bytes(self._string_bytes) + b'"')
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
                self.invalid = True
                return
            value = decoded if isinstance(decoded, str) else None
        self._string_role = ""
        if role == "key":
            parent = self._stack[-1]
            parent.key = value or UNKNOWN_KEY
            parent.state = "colon"
            return
        if value is not None and self._select(path):
            self._emit(path, value)
        self._complete_value()

    def _append_bare(self, byte: int) -> None:
        if len(self._bare_bytes) >= _BARE_VALUE_LIMIT:
            self.invalid = True
            return
        self._bare_bytes.append(byte)
        self._track_peak()

    def _finish_bare(self) -> None:
        try:
            value = json.loads(bytes(self._bare_bytes))
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            self.invalid = True
            return
        path = self._bare_path
        self._in_bare = False
        self._bare_bytes.clear()
        if self._select(path):
            self._emit(path, value)
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


__all__ = [
    "MAX_SCALAR_BYTES",
    "UNKNOWN_KEY",
    "JsonStreamWalker",
]
