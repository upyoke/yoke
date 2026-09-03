"""Thread-local process context for resident hook evaluation.

A hook historically ran in its own interpreter, so ``os.environ``, cwd, pid,
and stdio all described the harness child.  The resident evaluates concurrent
requests in threads; this module gives each thread that same process view
without mutating another request's view.
"""

from __future__ import annotations

import contextlib
import contextvars
import io
import os
import subprocess
import sys
from collections.abc import Iterator, MutableMapping
from dataclasses import dataclass
from typing import Any, BinaryIO, TextIO


_BASE_ENVIRONMENT = os.environ
_BASE_GETCWD = os.getcwd
_BASE_GETPID = os.getpid
_BASE_GETPPID = os.getppid
_BASE_POPEN = subprocess.Popen
_BASE_STDOUT = sys.stdout
_BASE_STDERR = sys.stderr


@dataclass(frozen=True)
class HookProcessContext:
    """The originating hook child's process facts."""

    environment: dict[str, str]
    cwd: str
    pid: int
    ppid: int


@dataclass
class _ActiveContext:
    process: HookProcessContext
    stdout_bytes: io.BytesIO
    stderr_bytes: io.BytesIO
    stdout: TextIO
    stderr: TextIO


_CURRENT: contextvars.ContextVar[_ActiveContext | None] = contextvars.ContextVar(
    "yoke_hook_process_context", default=None
)
_INSTALLED = False


def _active() -> _ActiveContext | None:
    return _CURRENT.get()


class _EnvironmentProxy(MutableMapping[str, str]):
    def _target(self) -> MutableMapping[str, str]:
        current = _active()
        return current.process.environment if current else _BASE_ENVIRONMENT

    def __getitem__(self, key: str) -> str:
        return self._target()[key]

    def __setitem__(self, key: str, value: str) -> None:
        self._target()[key] = value

    def __delitem__(self, key: str) -> None:
        del self._target()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._target())

    def __len__(self) -> int:
        return len(self._target())

    def copy(self) -> dict[str, str]:
        return dict(self._target())

    def __repr__(self) -> str:
        return repr(self._target())


class _BinaryStreamProxy:
    def __init__(self, default: BinaryIO, attribute: str) -> None:
        self._default = default
        self._attribute = attribute

    def _target(self) -> BinaryIO:
        current = _active()
        if current is None:
            return self._default
        return getattr(current, self._attribute).buffer

    def write(self, value: bytes) -> int:
        return self._target().write(value)

    def flush(self) -> None:
        self._target().flush()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._target(), name)


class _TextStreamProxy:
    def __init__(self, default: TextIO, attribute: str) -> None:
        self._default = default
        self._attribute = attribute
        default_buffer = getattr(default, "buffer", io.BytesIO())
        self.buffer = _BinaryStreamProxy(default_buffer, attribute)

    def _target(self) -> TextIO:
        current = _active()
        return getattr(current, self._attribute) if current else self._default

    def write(self, value: str) -> int:
        return self._target().write(value)

    def writelines(self, values) -> None:
        self._target().writelines(values)

    def flush(self) -> None:
        self._target().flush()

    def isatty(self) -> bool:
        return self._target().isatty()

    @property
    def encoding(self) -> str | None:
        return self._target().encoding

    @property
    def errors(self) -> str | None:
        return self._target().errors

    def __getattr__(self, name: str) -> Any:
        return getattr(self._target(), name)


class _ContextPopen(_BASE_POPEN):
    """Give hook subprocesses the caller's environment and cwd by default."""

    def __init__(self, *args, **kwargs) -> None:
        current = _active()
        if current is not None:
            kwargs.setdefault("env", dict(current.process.environment))
            kwargs.setdefault("cwd", current.process.cwd)
        super().__init__(*args, **kwargs)


def _getcwd() -> str:
    current = _active()
    return current.process.cwd if current else _BASE_GETCWD()


def _getpid() -> int:
    current = _active()
    return current.process.pid if current else _BASE_GETPID()


def _getppid() -> int:
    current = _active()
    return current.process.ppid if current else _BASE_GETPPID()


def install_process_context() -> None:
    """Install context-aware standard-library facades once in the daemon."""
    global _INSTALLED
    if _INSTALLED:
        return
    os.environ = _EnvironmentProxy()  # type: ignore[assignment]
    os.getcwd = _getcwd  # type: ignore[assignment]
    os.getpid = _getpid  # type: ignore[assignment]
    os.getppid = _getppid  # type: ignore[assignment]
    subprocess.Popen = _ContextPopen  # type: ignore[assignment]
    sys.stdout = _TextStreamProxy(_BASE_STDOUT, "stdout")  # type: ignore[assignment]
    sys.stderr = _TextStreamProxy(_BASE_STDERR, "stderr")  # type: ignore[assignment]
    _INSTALLED = True


@contextlib.contextmanager
def activate_process_context(
    process: HookProcessContext,
) -> Iterator["HookOutputCapture"]:
    """Activate one request and capture its stdout/stderr independently."""
    stdout_bytes = io.BytesIO()
    stderr_bytes = io.BytesIO()
    stdout = io.TextIOWrapper(
        stdout_bytes, encoding="utf-8", errors="replace", write_through=True
    )
    stderr = io.TextIOWrapper(
        stderr_bytes, encoding="utf-8", errors="replace", write_through=True
    )
    active = _ActiveContext(process, stdout_bytes, stderr_bytes, stdout, stderr)
    token = _CURRENT.set(active)
    capture = HookOutputCapture(active)
    try:
        yield capture
    finally:
        stdout.flush()
        stderr.flush()
        _CURRENT.reset(token)


class HookOutputCapture:
    """Read-only view of one active request's captured output."""

    def __init__(self, active: _ActiveContext) -> None:
        self._active_context = active

    def stdout_mark(self) -> int:
        self._active_context.stdout.flush()
        return self._active_context.stdout_bytes.tell()

    def stdout_since(self, offset: int) -> str:
        self._active_context.stdout.flush()
        return self._slice(self._active_context.stdout_bytes, offset)

    @property
    def stdout(self) -> str:
        self._active_context.stdout.flush()
        return self._slice(self._active_context.stdout_bytes, 0)

    @property
    def stderr(self) -> str:
        self._active_context.stderr.flush()
        return self._slice(self._active_context.stderr_bytes, 0)

    @staticmethod
    def _slice(stream: io.BytesIO, offset: int) -> str:
        position = stream.tell()
        stream.seek(max(0, offset))
        value = stream.read().decode("utf-8", errors="replace")
        stream.seek(position)
        return value


def active_output_capture() -> HookOutputCapture | None:
    current = _active()
    return HookOutputCapture(current) if current is not None else None


__all__ = [
    "HookOutputCapture",
    "HookProcessContext",
    "activate_process_context",
    "active_output_capture",
    "install_process_context",
]
