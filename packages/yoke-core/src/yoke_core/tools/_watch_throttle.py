"""Per-line-class progress throttling for watcher wrappers.

Watchers split the underlying command's output into four classes:

- ``URGENT`` — failures, errors, hard stops. Always emit immediately.
- ``SUMMARY`` — final banners, status transitions, completion signals.
  Always emit immediately.
- ``METADATA`` — wrapper headers and footers. Always emit immediately.
- ``PROGRESS`` — repetitive motion/heartbeat lines. Throttled by the
  shared :class:`ProgressGate`.

Lines that fall into none of those classes (``NOISE``) are written only
to the raw capture; they never reach the progress capture or wrapper
stdout.

This module owns the throttle math and the config loader so each watcher
wrapper only ships its own classifier — no per-wrapper cadence math, no
per-wrapper suppression counters, no per-wrapper config defaults.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass
from typing import Callable, Optional

from yoke_core.domain import runtime_settings


class LineClass(str, enum.Enum):
    """Output line classes recognised by the shared progress gate."""

    URGENT = "urgent"
    SUMMARY = "summary"
    METADATA = "metadata"
    PROGRESS = "progress"
    NOISE = "noise"


@dataclass(frozen=True)
class Classification:
    """A single line's class plus optional progress value.

    ``progress_value`` is the numeric axis (typically a percent in
    ``[0, 100]``) for progress lines that support delta-based throttling.
    Progress lines without a numeric axis (merge step banners, generic
    progress prefixes) leave it unset and rely on time-window throttling
    alone.
    """

    cls: LineClass
    progress_value: Optional[float] = None


@dataclass(frozen=True)
class ThrottlePolicy:
    """Throttle cadence for ``PROGRESS``-class lines.

    Numeric-axis progress lines (``Classification.progress_value`` set)
    rely on ``percent_step`` alone; the time window does not apply. Lines
    without a numeric axis fall back to ``min_interval_seconds``. The
    first progress line in a run always emits.
    """

    percent_step: float = 5.0
    min_interval_seconds: float = 10.0


CONFIG_KEY_PERCENT_STEP = "watcher_progress_percent_step"
CONFIG_KEY_MIN_INTERVAL = "watcher_progress_min_interval_seconds"

DEFAULT_PERCENT_STEP = 5.0
DEFAULT_MIN_INTERVAL_SECONDS = 10.0


def _read_throttle_config() -> dict[str, str]:
    """Return raw setting values for throttle keys from machine config."""
    keys = {CONFIG_KEY_PERCENT_STEP, CONFIG_KEY_MIN_INTERVAL}
    parsed = runtime_settings.read_all()
    return {k: v for k, v in parsed.items() if k in keys}


def _parse_positive_number(raw: str) -> Optional[float]:
    """Parse a strictly positive float; return ``None`` on bad input."""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return value


def load_throttle_policy() -> ThrottlePolicy:
    """Build a :class:`ThrottlePolicy` from machine config, with safe defaults.

    Invalid or missing values fall back to the module defaults — bad
    config NEVER suppresses urgent/error lines because urgent/error
    routing is not affected by the policy at all.
    """
    raw = _read_throttle_config()
    percent_step = (
        _parse_positive_number(raw.get(CONFIG_KEY_PERCENT_STEP, ""))
        or DEFAULT_PERCENT_STEP
    )
    min_interval = (
        _parse_positive_number(raw.get(CONFIG_KEY_MIN_INTERVAL, ""))
        or DEFAULT_MIN_INTERVAL_SECONDS
    )
    return ThrottlePolicy(
        percent_step=percent_step,
        min_interval_seconds=min_interval,
    )


@dataclass
class GateDecision:
    """Result of asking :class:`ProgressGate` whether to emit now."""

    emit: bool
    suppressed_count: int


class ProgressGate:
    """Per-run state for progress-class throttling.

    ``ProgressGate`` is created once per ``run_watcher`` invocation. It
    tracks the last emission time, the last emitted progress value (when
    available), and the suppression counter that gets attached to the
    next emitted progress line.
    """

    def __init__(
        self,
        policy: ThrottlePolicy,
        *,
        time_source: Callable[[], float] = time.monotonic,
    ) -> None:
        self._policy = policy
        self._now = time_source
        self._last_emit_time: Optional[float] = None
        self._last_emit_value: Optional[float] = None
        self._suppressed_since_emit: int = 0
        self._total_suppressed: int = 0

    def consider(self, classification: Classification) -> GateDecision:
        """Decide whether the current ``PROGRESS`` line should emit now.

        The first progress line in a run always emits. After that, a
        numeric-axis line (``classification.progress_value`` set) emits
        only when ``percent_step`` is crossed; a non-numeric line falls
        back to the ``min_interval_seconds`` time window. The first
        numeric line after a non-numeric emit primes the baseline so
        subsequent numeric ticks have a value to step from.
        """
        if classification.cls is not LineClass.PROGRESS:
            raise ValueError(
                "ProgressGate.consider only handles PROGRESS-class lines"
            )

        now = self._now()
        if self._last_emit_time is None:
            return self._emit(now, classification.progress_value)

        if classification.progress_value is not None:
            if self._last_emit_value is None:
                return self._emit(now, classification.progress_value)
            if (
                classification.progress_value - self._last_emit_value
                >= self._policy.percent_step
            ):
                return self._emit(now, classification.progress_value)
        else:
            if (
                now - self._last_emit_time
            ) >= self._policy.min_interval_seconds:
                return self._emit(now, None)

        self._suppressed_since_emit += 1
        self._total_suppressed += 1
        return GateDecision(emit=False, suppressed_count=0)

    def _emit(
        self, now: float, value: Optional[float]
    ) -> GateDecision:
        suppressed = self._suppressed_since_emit
        self._suppressed_since_emit = 0
        self._last_emit_time = now
        if value is not None:
            self._last_emit_value = value
        return GateDecision(emit=True, suppressed_count=suppressed)

    @property
    def total_suppressed(self) -> int:
        """Total progress lines suppressed across the entire run."""
        return self._total_suppressed

    @property
    def pending_suppressed(self) -> int:
        """Progress lines suppressed since the most recent emission.

        Used when the run finishes mid-window so the wrapper footer can
        report the residual count.
        """
        return self._suppressed_since_emit


def annotate_progress_line(line: str, suppressed_count: int) -> str:
    """Append a ``(suppressed N ticks)`` marker to a progress line.

    The annotation is attached only when ``suppressed_count > 0``. The
    raw capture is never annotated — only the progress capture and
    wrapper stdout receive the marker.
    """
    if suppressed_count <= 0:
        return line
    suffix = f" (suppressed {suppressed_count} ticks)"
    if line.endswith("\n"):
        return line[:-1] + suffix + "\n"
    return line + suffix
