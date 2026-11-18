"""Install a newly served relay release beside the poll loop, never inside it.

The standing relay keeps claiming wakes on its current release while the next
one installs: one background thread owned by the daemon runs the pin, and the
loop only asks whether it has finished. A failed pin is recorded once per
served build; the same build is not retried until a new build is served or
``yoke relay install`` restarts the service. Stopping the daemon kills the
install's child processes instead of waiting for them.

The in-flight install and the last failure are kept in the machine-local
relay health document, beside the poll outcome, for ``yoke relay status``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import logging
from pathlib import Path
import subprocess
import threading
import time
from typing import Any

from yoke_contracts.timestamps import iso8601_now, parse_instant, utc_now
from yoke_harness.session_relay_failure_log import FailureReporter
from yoke_harness.session_relay_health import _LOCK, _health_path, _load, _write

RELEASE_PIN_CANCELLED = "relay_release_install_cancelled"

_LOGGER = logging.getLogger(__name__)

# Longest a stopping daemon waits for a killed install to remove its candidate.
# A candidate left behind is pruned by the next verified install.
CANCEL_SETTLE_SECONDS = 1.0

Runner = Callable[..., subprocess.CompletedProcess[str]]
PinServedRelease = Callable[..., Path]


class ReleasePinCancelled(RuntimeError):
    """The relay stopped while its next release was still installing."""

    code = RELEASE_PIN_CANCELLED


class InterruptibleRunner:
    """``subprocess.run`` whose live children the daemon can kill."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._children: set[subprocess.Popen[Any]] = set()
        self._cancelled = False

    def __call__(
        self,
        args: Any,
        *,
        check: bool = False,
        capture_output: bool = False,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[Any]:
        if capture_output:
            kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        with self._lock:
            self._refuse_if_cancelled()
            child = subprocess.Popen(args, **kwargs)
            self._children.add(child)
        try:
            try:
                stdout, stderr = child.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                child.kill()
                child.communicate()
                raise
        finally:
            with self._lock:
                self._children.discard(child)
        with self._lock:
            self._refuse_if_cancelled()
        result = subprocess.CompletedProcess(args, child.returncode, stdout, stderr)
        if check:
            result.check_returncode()
        return result

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True
            children = list(self._children)
        for child in children:
            try:
                child.kill()
            except OSError:
                pass

    def _refuse_if_cancelled(self) -> None:
        if self._cancelled:
            raise ReleasePinCancelled(
                "the relay stopped while the release was installing; "
                "the next relay start retries the pin"
            )


@dataclass
class _Attempt:
    served_build: str
    runner: InterruptibleRunner
    thread: threading.Thread
    started: float = 0.0
    polls: int = 0
    replacement: Path | None = None
    error: BaseException | None = None


class ReleasePinner:
    """One single-flight background release install for the standing daemon."""

    def __init__(
        self,
        pin_served_release: PinServedRelease,
        *,
        pinned_release: str,
        state_dir: Path,
        failures: FailureReporter,
    ) -> None:
        self._pin = pin_served_release
        self._pinned_release = pinned_release
        self._state_dir = state_dir
        self._failures = failures
        self._attempt: _Attempt | None = None
        self._failed_build = ""
        clear_release_pin(state_dir)

    def offer(self, served_build: str) -> None:
        """Start installing a newly served build unless one runs or it failed."""
        if (
            not (self._pinned_release and served_build)
            or served_build in {self._pinned_release, self._failed_build}
            or self._attempt is not None
        ):
            return
        attempt = _Attempt(
            served_build, InterruptibleRunner(), threading.Thread(), time.monotonic()
        )
        attempt.thread = threading.Thread(
            target=self._run,
            args=(attempt,),
            name=f"relay-release-pin-{served_build}",
            daemon=True,
        )
        self._attempt = attempt
        record_release_pin_started(self._state_dir, served_build)
        _LOGGER.warning(
            "%s relay release install started for %s; "
            "class=relay_release_install outcome=installing",
            iso8601_now(),
            served_build,
        )
        attempt.thread.start()

    def settle(self) -> Path | None:
        """Return the replacement once a pin succeeds; record a failure once."""
        attempt = self._attempt
        if attempt is None:
            return None
        if attempt.thread.is_alive():
            attempt.polls += 1
            return None
        self._attempt = None
        _LOGGER.warning(
            "%s relay release install %s for %s; class=relay_release_install "
            "elapsed_seconds=%.1f polls_during_install=%d outcome=%s",
            iso8601_now(),
            "failed" if attempt.error is not None else "verified",
            attempt.served_build,
            time.monotonic() - attempt.started,
            attempt.polls,
            "kept_prior_release" if attempt.error is not None else "switching",
        )
        if attempt.error is not None:
            exc = attempt.error
            code = str(getattr(exc, "code", "") or "release_pin_failed")
            self._failed_build = attempt.served_build
            self._failures.failed("release pin", f"{code}: {exc}")
            record_release_pin_failed(self._state_dir, attempt.served_build, code)
            return None
        self._failures.recovered("release pin")
        clear_release_pin(self._state_dir)
        return attempt.replacement

    def cancel(self, timeout: float) -> None:
        """Kill the install's children and let it clean up its candidate."""
        attempt = self._attempt
        if attempt is None:
            return
        attempt.runner.cancel()
        attempt.thread.join(min(max(0.0, timeout), CANCEL_SETTLE_SECONDS))

    def _run(self, attempt: _Attempt) -> None:
        try:
            attempt.replacement = self._pin(attempt.served_build, runner=attempt.runner)
        except BaseException as exc:  # noqa: BLE001 — reported by settle()
            attempt.error = exc


def record_release_pin_started(state_dir: Path, served_build: str) -> None:
    _replace_release_pin(
        state_dir,
        in_flight={"served_build": served_build, "started_at": iso8601_now()},
    )


def record_release_pin_failed(state_dir: Path, served_build: str, code: str) -> None:
    _replace_release_pin(
        state_dir,
        in_flight=None,
        last_failure={
            "served_build": served_build,
            "error_code": code,
            "failed_at": iso8601_now(),
        },
    )


def clear_release_pin(state_dir: Path) -> None:
    with _LOCK:
        path = _health_path(state_dir)
        document = _load(path)
        if document.pop("release_pin", None) is not None:
            _write(path, document)


def _replace_release_pin(state_dir: Path, **update: object) -> None:
    with _LOCK:
        path = _health_path(state_dir)
        document = _load(path)
        previous = document.get("release_pin")
        pin = dict(previous) if isinstance(previous, Mapping) else {}
        for key, value in update.items():
            if value is None:
                pin.pop(key, None)
            else:
                pin[key] = value
        document["release_pin"] = pin
        _write(path, document)


def attach_release_pin(
    health: dict[str, object], document: Mapping[str, object]
) -> dict[str, object]:
    """Copy the local release install state onto observed relay health."""
    pin = document.get("release_pin")
    if not isinstance(pin, Mapping):
        return health
    observed: dict[str, object] = {}
    in_flight = pin.get("in_flight")
    if isinstance(in_flight, Mapping) and in_flight.get("served_build"):
        started_at = str(in_flight.get("started_at") or "")
        entry: dict[str, object] = {
            "served_build": str(in_flight["served_build"]),
            "started_at": started_at,
        }
        try:
            elapsed = (utc_now() - parse_instant(started_at)).total_seconds()
            entry["elapsed_seconds"] = max(0, int(elapsed))
        except (TypeError, ValueError):
            pass
        observed["in_flight"] = entry
    failure = pin.get("last_failure")
    if isinstance(failure, Mapping) and failure.get("served_build"):
        observed["last_failure"] = {
            key: str(failure.get(key) or "")
            for key in ("served_build", "error_code", "failed_at")
        }
    if observed:
        health["release_pin"] = observed
    return health


__all__ = [
    "RELEASE_PIN_CANCELLED",
    "InterruptibleRunner",
    "ReleasePinCancelled",
    "ReleasePinner",
    "attach_release_pin",
    "clear_release_pin",
]
