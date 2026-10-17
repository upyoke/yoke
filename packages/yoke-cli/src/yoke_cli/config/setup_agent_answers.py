"""The in-progress agent setup on this machine: presets, answers, and where it waits.

Agent mode runs one question per invocation, so what was already answered has
to outlive the process. The store keeps the preset flags the run started with,
a ``key -> value`` map of accepted answers, the question the run stopped at,
and the Apply failure an answer may resume. Answers are keyed by question, not
by position, because saved machine state can skip whole steps on a later run.
Secret values never reach this file: a secret answer is refused before it is
staged. One invocation at a time holds the store's lock.
"""

from __future__ import annotations

import fcntl
import json
import os
import stat
from pathlib import Path
from typing import Any

from yoke_contracts.machine_config.directories import create_private_directory

from yoke_cli.config import onboard_checklist

STORE_NAME = "agent-setup.json"
LOCK_NAME = "agent-setup.lock"
STORE_VERSION = 1
STORE_MODE = 0o600


class AnswerStoreError(RuntimeError):
    """A named agent-setup refusal: ``reason`` plus the recovery to take."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def store_path() -> Path:
    return onboard_checklist.runs_dir() / STORE_NAME


def discard() -> bool:
    """Delete the in-progress agent setup; False when there was none.

    The caller holds the store's lock already.
    """
    try:
        store_path().unlink()
    except FileNotFoundError:
        return False
    return True


def discard_saved() -> bool:
    """Take the lock and delete the store, even one too damaged to load."""
    lock_fd = _lock()
    try:
        return discard()
    finally:
        os.close(lock_fd)


class AnswerStore:
    """One invocation's view of the store: saved answers plus staged ones.

    Accepted answers are staged and reach disk only through :meth:`flush`, so
    an invocation that ends in a refusal leaves the store exactly as it was.
    """

    def __init__(self, record: dict[str, Any], *, existed: bool) -> None:
        self.existed = existed
        self.presets: dict[str, Any] = dict(record.get("presets") or {})
        self.answers: dict[str, str] = dict(record.get("answers") or {})
        self.waiting_key: str | None = record.get("waiting_key")
        self.apply_failure: dict[str, Any] | None = record.get("apply_failure")
        self._staged: dict[str, str] = {}
        self._dropped: set[str] = set()
        self._lock_fd: int | None = None

    # ── reading ─────────────────────────────────────────────

    def value(self, key: str) -> str | None:
        if key in self._staged:
            return self._staged[key]
        if key in self._dropped:
            return None
        return self.answers.get(key)

    def values_for(self, key: str) -> dict[str, str]:
        """The stored answer for ``key`` and for each of its form fields."""
        prefix = f"{key}."
        names = {*self.answers, *self._staged} - self._dropped
        found = {
            name: self.value(name)
            for name in names
            if name == key or name.startswith(prefix)
        }
        return {name: value for name, value in found.items() if value is not None}

    # ── writing ─────────────────────────────────────────────

    def stage(self, values: dict[str, str]) -> None:
        self._staged.update(values)

    def drop(self, key: str) -> None:
        """Forget a stored answer the current machine state no longer accepts."""
        prefix = f"{key}."
        for name in [*self.answers, *self._staged]:
            if name == key or name.startswith(prefix):
                self._staged.pop(name, None)
                self._dropped.add(name)

    def flush(self, *, waiting_key: str | None = None) -> None:
        answers = {
            name: value
            for name, value in {**self.answers, **self._staged}.items()
            if name not in self._dropped or name in self._staged
        }
        self.answers = answers
        self._staged = {}
        self._dropped = set()
        self.waiting_key = waiting_key
        record = {
            "version": STORE_VERSION,
            "presets": self.presets,
            "answers": answers,
            "waiting_key": waiting_key,
            "apply_failure": self.apply_failure,
        }
        _write_private(
            store_path(), json.dumps(record, indent=2, sort_keys=True) + "\n"
        )
        self.existed = True

    def wait_at(self, key: str) -> None:
        """Wait at the question a refusal repeats; saved answers stay as they were."""
        if not self.existed or key == self.waiting_key:
            return
        self._staged = {}
        self._dropped = set()
        self.flush(waiting_key=key)

    def release(self) -> None:
        if self._lock_fd is not None:
            os.close(self._lock_fd)
            self._lock_fd = None


def open_store() -> AnswerStore:
    """Lock and load the store; refuse a busy, unreadable or foreign one."""
    lock_fd = _lock()
    try:
        record, existed = _load(store_path())
    except AnswerStoreError:
        os.close(lock_fd)
        raise
    store = AnswerStore(record, existed=existed)
    store._lock_fd = lock_fd
    return store


def _lock() -> int:
    """Hold the one-invocation-at-a-time lock; refuse when another holds it."""
    directory = store_path().parent
    create_private_directory(directory)
    lock_fd = os.open(directory / LOCK_NAME, os.O_CREAT | os.O_RDWR, STORE_MODE)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        os.close(lock_fd)
        raise AnswerStoreError(
            "setup_agent_busy",
            "another `yoke setup --agent` invocation is running; wait for it to finish",
        ) from exc
    return lock_fd


def _load(path: Path) -> tuple[dict[str, Any], bool]:
    try:
        info = path.stat()
    except FileNotFoundError:
        return {}, False
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise _unreadable(f"{path} must be owned by you with mode 0600")
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise _unreadable(f"{path} is not readable JSON ({exc})") from exc
    if not isinstance(record, dict) or record.get("version") != STORE_VERSION:
        raise _unreadable(f"{path} is not a version {STORE_VERSION} agent setup")
    return record, True


def _unreadable(detail: str) -> AnswerStoreError:
    return AnswerStoreError(
        "setup_agent_store_unreadable",
        f"the saved agent setup cannot be used: {detail}; "
        "run `yoke setup --agent --discard` and start again",
    )


def _write_private(path: Path, text: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    fd = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, STORE_MODE)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(temporary, STORE_MODE)
    os.replace(temporary, path)


__all__ = [
    "AnswerStore",
    "AnswerStoreError",
    "STORE_MODE",
    "discard",
    "discard_saved",
    "open_store",
    "store_path",
]
