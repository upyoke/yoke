"""Absolute-deadline reads for urllib response bodies."""

from __future__ import annotations

import io
import math
import time
from collections.abc import Callable
from typing import Any, BinaryIO


monotonic = time.monotonic


class ResponseReadError(ValueError):
    """A response reader did not provide a bounded byte stream."""


class ResponseReadDeadlineError(ResponseReadError):
    """A response body did not finish before its absolute deadline."""


def deadline_after(
    timeout_seconds: float,
    *,
    clock: Callable[[], float] | None = None,
) -> float:
    """Return an absolute monotonic deadline for a positive finite timeout."""
    try:
        timeout = float(timeout_seconds)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("response timeout must be positive and finite") from exc
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("response timeout must be positive and finite")
    return (clock or monotonic)() + timeout


def read_response_body(
    response: Any,
    *,
    limit_bytes: int,
    deadline: float,
    clock: Callable[[], float] | None = None,
) -> bytes:
    """Read through one overflow byte while enforcing an absolute deadline."""
    if isinstance(limit_bytes, bool) or not isinstance(limit_bytes, int):
        raise ValueError("response byte limit must be a positive integer")
    if limit_bytes <= 0:
        raise ValueError("response byte limit must be a positive integer")
    if not math.isfinite(deadline):
        raise ValueError("response deadline must be finite")

    selected_clock = clock or monotonic
    read = getattr(response, "read", None)
    if not callable(read):
        raise ResponseReadError("response reader did not return bytes")
    read1 = getattr(response, "read1", None)
    if not _supports_incremental_read(response, read1):
        _set_remaining_socket_timeout(response, deadline, selected_clock)
        try:
            raw = read(limit_bytes + 1)
        except TimeoutError:
            raise ResponseReadDeadlineError(
                "response body exceeded its time limit"
            ) from None
        _check_deadline(deadline, selected_clock)
        return _as_bytes(raw)

    chunks: list[bytes] = []
    remaining_bytes = limit_bytes + 1
    while remaining_bytes > 0:
        _set_remaining_socket_timeout(response, deadline, selected_clock)
        try:
            chunk = _as_bytes(read1(remaining_bytes))
        except TimeoutError:
            raise ResponseReadDeadlineError(
                "response body exceeded its time limit"
            ) from None
        _check_deadline(deadline, selected_clock)
        if not chunk:
            break
        chunks.append(chunk)
        remaining_bytes -= len(chunk)
    return b"".join(chunks)


def copy_response_body(
    response: Any,
    destination: BinaryIO,
    *,
    limit_bytes: int,
    deadline: float,
    clock: Callable[[], float] | None = None,
    chunk_bytes: int = 1024 * 1024,
) -> int:
    """Stream a bounded response into ``destination`` under one deadline."""
    if isinstance(limit_bytes, bool) or not isinstance(limit_bytes, int):
        raise ValueError("response byte limit must be a positive integer")
    if limit_bytes <= 0 or chunk_bytes <= 0:
        raise ValueError("response and chunk byte limits must be positive")
    if not math.isfinite(deadline):
        raise ValueError("response deadline must be finite")
    selected_clock = clock or monotonic
    read = getattr(response, "read1", None)
    if not callable(read):
        read = getattr(response, "read", None)
    if not callable(read):
        raise ResponseReadError("response reader did not return bytes")
    written = 0
    while True:
        _set_remaining_socket_timeout(response, deadline, selected_clock)
        try:
            chunk = _as_bytes(read(min(chunk_bytes, limit_bytes - written + 1)))
        except TimeoutError:
            raise ResponseReadDeadlineError(
                "response body exceeded its time limit"
            ) from None
        _check_deadline(deadline, selected_clock)
        if not chunk:
            return written
        written += len(chunk)
        if written > limit_bytes:
            raise ResponseReadError("response body exceeded its byte limit")
        destination.write(chunk)


def _as_bytes(raw: Any) -> bytes:
    if not isinstance(raw, (bytes, bytearray, memoryview)):
        raise ResponseReadError("response reader did not return bytes")
    return bytes(raw)


def _supports_incremental_read(response: Any, read1: Any) -> bool:
    if not callable(read1) or isinstance(response, io.BytesIO):
        return False
    try:
        wrapped = getattr(response, "fp", None)
    except Exception:
        return False
    return not isinstance(wrapped, io.BytesIO)


def _check_deadline(deadline: float, clock: Callable[[], float]) -> None:
    if clock() >= deadline:
        raise ResponseReadDeadlineError("response body exceeded its time limit")


def _set_remaining_socket_timeout(
    response: Any,
    deadline: float,
    clock: Callable[[], float],
) -> None:
    """Best-effort shorten the underlying socket timeout to time remaining."""
    remaining = deadline - clock()
    if remaining <= 0:
        raise ResponseReadDeadlineError("response body exceeded its time limit")

    pending = [response]
    seen: set[int] = set()
    while pending:
        candidate = pending.pop()
        identity = id(candidate)
        if identity in seen:
            continue
        seen.add(identity)
        setter = getattr(candidate, "settimeout", None)
        if callable(setter):
            try:
                setter(remaining)
            except Exception:
                pass
            else:
                return
        if len(seen) >= 8:
            continue
        for attribute in ("fp", "raw", "_sock", "sock"):
            try:
                nested = getattr(candidate, attribute, None)
            except Exception:
                continue
            if nested is not None:
                pending.append(nested)


__all__ = [
    "ResponseReadDeadlineError",
    "ResponseReadError",
    "copy_response_body",
    "deadline_after",
    "read_response_body",
]
