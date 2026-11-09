"""Report when a watcher's progress capture is held while the child still moves.

Percent-step throttling can leave the progress file at 90% for minutes while
raw keeps printing dots. Agents that only follow progress then interrupt a
healthy suite. This watch wakes on a bound between *emitted* progress lines
and names the mirage so the run stays diagnosable without raising timeouts.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


PROGRESS_STALL_SECONDS_ENV = "YOKE_WATCH_PROGRESS_STALL_SECONDS"
DEFAULT_PROGRESS_STALL_SECONDS = 300.0


def progress_stall_seconds(env: dict[str, str] | None = None) -> float:
    """Seconds without an emitted progress line before a throttle report."""
    raw = (env or os.environ).get(PROGRESS_STALL_SECONDS_ENV)
    if raw is None:
        return DEFAULT_PROGRESS_STALL_SECONDS
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(
            f"{PROGRESS_STALL_SECONDS_ENV} must be a positive number"
        ) from exc
    if value <= 0:
        raise ValueError(
            f"{PROGRESS_STALL_SECONDS_ENV} must be a positive number"
        )
    return value


@dataclass
class ProgressEmitWatch:
    """Detect when the progress capture is held while the child still moves."""

    kind: str
    stall_seconds: float
    _started_at: float
    _last_output_at: float
    _last_progress_at: float
    _last_report_at: float
    _last_progress_value: Optional[float] = None

    @classmethod
    def start(cls, kind: str, *, now: float) -> "ProgressEmitWatch":
        return cls(
            kind=kind,
            stall_seconds=progress_stall_seconds(),
            _started_at=now,
            _last_output_at=now,
            _last_progress_at=now,
            _last_report_at=now,
        )

    def note_output(self, now: float) -> None:
        self._last_output_at = now

    def note_progress_emit(
        self, now: float, progress_value: Optional[float] = None
    ) -> None:
        self._last_progress_at = now
        self._last_report_at = now
        if progress_value is not None:
            self._last_progress_value = progress_value

    def next_wait_seconds(
        self, now: float, *, quiet_seconds: float, deadline: float | None
    ) -> float:
        until_report = max(
            0.0, self.stall_seconds - (now - self._last_report_at)
        )
        wait = min(
            quiet_seconds,
            until_report if until_report > 0 else self.stall_seconds,
        )
        if deadline is not None:
            wait = min(wait, max(0.0, deadline - now))
        return wait

    def report_if_stalled(self, now: float) -> Optional[str]:
        """Return a progress-stall line, or None when still within bounds."""
        progress_age = now - self._last_progress_at
        if progress_age < self.stall_seconds:
            return None
        if now - self._last_report_at < self.stall_seconds:
            return None
        output_age = now - self._last_output_at
        last = (
            f"{self._last_progress_value:g}%"
            if self._last_progress_value is not None
            else "none"
        )
        if output_age < self.stall_seconds:
            waiting = (
                "progress_throttle "
                "(progress capture held at last percent while child still moves)"
            )
            child_bit = f"child output {output_age:.0f}s ago"
        else:
            waiting = "child_process"
            child_bit = f"no child output for {output_age:.0f}s"
        self._last_report_at = now
        return (
            f"# watch_{self.kind} no progress for {progress_age:.0f}s; "
            f"last reported {last}; {child_bit}; waiting_on={waiting}\n"
        )


__all__ = [
    "DEFAULT_PROGRESS_STALL_SECONDS",
    "PROGRESS_STALL_SECONDS_ENV",
    "ProgressEmitWatch",
    "progress_stall_seconds",
]
