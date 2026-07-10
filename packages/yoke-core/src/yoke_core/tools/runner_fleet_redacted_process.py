"""Concurrent secret-redacting process streaming for runner-fleet tools."""

from __future__ import annotations

import codecs
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import os
import signal
import subprocess
from threading import Thread
from typing import Any, BinaryIO, TextIO


_REDACTED = b"[REDACTED]"
_STREAM_CHUNK_SIZE = 8192


class RedactedProcessError(RuntimeError):
    """A child process could not be streamed without exposing secrets."""


@dataclass(frozen=True)
class RedactedChildResult:
    returncode: int


class _StreamingRedactor:
    """Redact exact byte terms without leaking matches across reads."""

    def __init__(self, terms: Sequence[str]) -> None:
        self._terms = tuple(
            term.encode("utf-8") for term in terms if term
        )
        self._retained = b""
        self._max_term_length = max(
            (len(term) for term in self._terms), default=1,
        )

    def feed(self, chunk: bytes) -> bytes:
        combined = self._retained + chunk
        retained_length = self._max_term_length - 1
        if len(combined) <= retained_length:
            self._retained = combined
            return b""
        split_at = self._safe_split(combined, retained_length)
        ready = combined[:split_at]
        self._retained = combined[split_at:]
        return self._redact(ready)

    def finish(self) -> bytes:
        ready = self._redact(self._retained)
        self._retained = b""
        return ready

    def _redact(self, value: bytes) -> bytes:
        for term in self._terms:
            value = value.replace(term, _REDACTED)
        return value

    def _safe_split(self, value: bytes, retained_length: int) -> int:
        split_at = len(value) - retained_length
        while split_at:
            adjusted = split_at
            for term in self._terms:
                search_from = max(0, split_at - len(term) + 1)
                occurrence = value.find(term, search_from)
                while 0 <= occurrence < split_at:
                    if occurrence + len(term) > split_at:
                        adjusted = min(adjusted, occurrence)
                        break
                    occurrence = value.find(term, occurrence + 1)
            if adjusted == split_at:
                return split_at
            split_at = adjusted
        return 0


def run_redacted_child(
    command: Sequence[str],
    *,
    env: Mapping[str, str],
    redaction_terms: Sequence[str],
    child_factory: Callable[..., Any] = subprocess.Popen,
    out: TextIO,
    err: TextIO,
) -> RedactedChildResult:
    """Run a non-interactive child and forward both streams concurrently."""
    try:
        process = child_factory(
            list(command),
            env=dict(env),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            start_new_session=True,
        )
    except FileNotFoundError:
        raise
    except Exception as exc:
        raise RedactedProcessError(
            "runner-fleet child command could not be executed"
        ) from exc

    stdout_pipe = getattr(process, "stdout", None)
    stderr_pipe = getattr(process, "stderr", None)
    if stdout_pipe is None or stderr_pipe is None:
        _stop_process(process)
        raise RedactedProcessError(
            "runner-fleet child command streams could not be captured"
        )

    pump_failures: list[bool] = []
    pumps = (
        Thread(
            target=_pump_redacted_stream,
            args=(stdout_pipe, out, redaction_terms, pump_failures),
            daemon=True,
        ),
        Thread(
            target=_pump_redacted_stream,
            args=(stderr_pipe, err, redaction_terms, pump_failures),
            daemon=True,
        ),
    )
    for pump in pumps:
        pump.start()
    wait_failure = False
    try:
        returncode = int(process.wait())
    except KeyboardInterrupt:
        _stop_process(process)
        raise
    except Exception:
        wait_failure = True
        returncode = 1
        _stop_process(process)
    finally:
        for pump in pumps:
            pump.join()
    if wait_failure:
        raise RedactedProcessError(
            "runner-fleet child command could not be awaited"
        )
    if pump_failures:
        raise RedactedProcessError(
            "runner-fleet child output could not be streamed safely"
        )
    return RedactedChildResult(returncode=returncode)


def _pump_redacted_stream(
    source: BinaryIO,
    destination: TextIO,
    terms: Sequence[str],
    failures: list[bool],
) -> None:
    redactor = _StreamingRedactor(terms)
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    destination_available = True
    try:
        while True:
            chunk = source.read(_STREAM_CHUNK_SIZE)
            if not chunk:
                break
            destination_available = _forward_bytes(
                redactor.feed(chunk),
                decoder=decoder,
                destination=destination,
                destination_available=destination_available,
                failures=failures,
                final=False,
            )
        _forward_bytes(
            redactor.finish(),
            decoder=decoder,
            destination=destination,
            destination_available=destination_available,
            failures=failures,
            final=True,
        )
    except Exception:
        failures.append(True)
    finally:
        try:
            source.close()
        except Exception:
            failures.append(True)


def _forward_bytes(
    value: bytes,
    *,
    decoder: codecs.IncrementalDecoder,
    destination: TextIO,
    destination_available: bool,
    failures: list[bool],
    final: bool,
) -> bool:
    text = decoder.decode(value, final=final)
    if not text or not destination_available:
        return destination_available
    try:
        destination.write(text)
        destination.flush()
    except Exception:
        failures.append(True)
        return False
    return True


def _stop_process(process: Any) -> None:
    _signal_process(process, signal.SIGTERM, "terminate")
    try:
        process.wait(timeout=5)
        return
    except BaseException:
        pass
    _signal_process(process, signal.SIGKILL, "kill")
    try:
        process.wait()
    except BaseException:
        pass


def _signal_process(process: Any, group_signal: int, method: str) -> None:
    pid = getattr(process, "pid", None)
    if isinstance(pid, int) and pid > 0:
        try:
            os.killpg(pid, group_signal)
            return
        except OSError:
            pass
    try:
        getattr(process, method)()
    except Exception:
        pass


__all__ = [
    "RedactedChildResult",
    "RedactedProcessError",
    "run_redacted_child",
]
