"""Per-line-class classification and progress throttling for watchers.

Watchers split the underlying command's output into two wake tiers,
expressed as five line classes:

- ``URGENT`` — failures, errors, denials, refusals, hard stops.
- ``SUMMARY`` — final banners and terminal outcomes.
- ``METADATA`` — wrapper headers and footers.

  Those three are the immediate tier: each one reaches the follower the
  moment it arrives, carrying whatever progress was buffered before it.

- ``PROGRESS`` — motion: stage boundaries, run and workflow ids,
  rehearsal verdicts, percentages, status polls. Batched by
  :class:`yoke_core.tools._watch_digest.ProgressDigest` into one digest
  line per flush window, so a long run costs a wake every couple of
  minutes rather than one wake per line.

Lines that fall into none of those classes (``NOISE``) are written only
to the raw capture; they never reach the progress capture or wrapper
stdout.

Inside the progress tier the two axes behave differently, which is what
:class:`ProgressGate` owns. A numeric-axis line *supersedes* its
predecessors — ``[ 47%]`` says everything ``[ 46%]`` did — so only a
line that crosses ``percent_step`` is worth carrying, and the ones it
supersedes are counted rather than kept. A line with no numeric axis
carries content nothing else repeats — which database passed, which
stage opened — so every one of them is kept and the digest window, not a
drop, is what keeps the wake count down.

This module owns the class taxonomy and that supersession math so each
watcher wrapper ships only its own classifier.
"""

from __future__ import annotations

import enum
import re
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
    ``[0, 100]``) for progress lines that supersede their predecessors.
    Progress lines without a numeric axis (merge step banners, database
    verdicts, stage boundaries) leave it unset and are all carried into
    the digest.
    """

    cls: LineClass
    progress_value: Optional[float] = None


#: A watcher wrapper's own line classifier.
Classifier = Callable[[str], Classification]


def filter_match(pattern: re.Pattern[str], line: str) -> bool:
    """Return True when *line* matches *pattern*.

    Retained for classifier authors that want to compose a class
    decision out of a regex pre-check. Line-oriented; callers compose
    the regex without ``re.MULTILINE``.
    """
    return bool(pattern.search(line))


def regex_classifier(pattern: re.Pattern[str]) -> Classifier:
    """Adapt a single regex into a classifier.

    Matching lines are classified as ``PROGRESS`` with no numeric value
    (so every match is carried into the digest); non-matching lines are
    ``NOISE``. Provided so callers without a richer taxonomy can still
    reach the shared tiers.
    """

    def _classify(line: str) -> Classification:
        if pattern.search(line):
            return Classification(LineClass.PROGRESS)
        return Classification(LineClass.NOISE)

    return _classify


@dataclass(frozen=True)
class ThrottlePolicy:
    """Supersession step for numeric-axis ``PROGRESS`` lines.

    A numeric-axis line emits only once it has advanced ``percent_step``
    past the last one carried. Lines with no numeric axis are all
    carried; the digest window is what bounds their wake cost.
    """

    percent_step: float = 5.0


CONFIG_KEY_PERCENT_STEP = "watcher_progress_percent_step"

DEFAULT_PERCENT_STEP = 5.0


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
    """Build a :class:`ThrottlePolicy` from machine config, with a safe default.

    An invalid or missing value falls back to the module default — bad
    config NEVER suppresses urgent/error lines because urgent/error
    routing is not affected by the policy at all.
    """
    raw = runtime_settings.read_all().get(CONFIG_KEY_PERCENT_STEP, "")
    percent_step = _parse_positive_number(raw) or DEFAULT_PERCENT_STEP
    return ThrottlePolicy(percent_step=percent_step)


@dataclass
class GateDecision:
    """Result of asking :class:`ProgressGate` whether to carry a line."""

    emit: bool
    suppressed_count: int


class ProgressGate:
    """Per-run supersession state for numeric ``PROGRESS`` lines.

    ``ProgressGate`` is created once per ``run_watcher`` invocation. It
    tracks the last carried progress value and the supersession counter
    that gets attached to the next carried progress line.
    """

    def __init__(
        self,
        policy: ThrottlePolicy,
        *,
        time_source: Callable[[], float] = time.monotonic,
    ) -> None:
        self._policy = policy
        self._now = time_source
        self._carried_any = False
        self._last_emit_value: Optional[float] = None
        self._suppressed_since_emit: int = 0
        self._total_suppressed: int = 0

    def consider(self, classification: Classification) -> GateDecision:
        """Decide whether the current ``PROGRESS`` line should be carried.

        The first progress line in a run is always carried. After that, a
        numeric-axis line (``classification.progress_value`` set) is
        carried only when ``percent_step`` is crossed, because the ticks
        between say nothing the newer one does not. A line with no
        numeric axis carries its own content and is always kept. The
        first numeric line after a non-numeric one primes the baseline so
        subsequent ticks have a value to step from.
        """
        if classification.cls is not LineClass.PROGRESS:
            raise ValueError(
                "ProgressGate.consider only handles PROGRESS-class lines"
            )

        if not self._carried_any:
            return self._emit(classification.progress_value)

        if classification.progress_value is None:
            return self._emit(None)
        if self._last_emit_value is None:
            return self._emit(classification.progress_value)
        if (
            classification.progress_value - self._last_emit_value
            >= self._policy.percent_step
        ):
            return self._emit(classification.progress_value)

        self._suppressed_since_emit += 1
        self._total_suppressed += 1
        return GateDecision(emit=False, suppressed_count=0)

    def _emit(self, value: Optional[float]) -> GateDecision:
        suppressed = self._suppressed_since_emit
        self._suppressed_since_emit = 0
        self._carried_any = True
        if value is not None:
            self._last_emit_value = value
        return GateDecision(emit=True, suppressed_count=suppressed)

    @property
    def total_suppressed(self) -> int:
        """Total superseded progress ticks across the entire run."""
        return self._total_suppressed

    @property
    def pending_suppressed(self) -> int:
        """Ticks superseded since the most recent carried line.

        Used when the run finishes mid-window so the wrapper footer can
        report the residual count.
        """
        return self._suppressed_since_emit


def annotate_progress_line(line: str, suppressed_count: int) -> str:
    """Append a ``(suppressed N ticks)`` marker to a progress line.

    The annotation is attached only when ``suppressed_count > 0``. The
    raw capture is never annotated — only the digest that carries this
    line, the progress capture, and wrapper stdout receive the marker.
    """
    if suppressed_count <= 0:
        return line
    suffix = f" (suppressed {suppressed_count} ticks)"
    if line.endswith("\n"):
        return line[:-1] + suffix + "\n"
    return line + suffix
