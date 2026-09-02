"""Batching of watcher progress lines, and the flush window that bounds it.

Every progress line a watcher emitted used to be one wake. A steering
seat driving two deployment runs therefore spent a dozen one-line turns
per pair on stage boundaries, workflow ids, and rehearsal verdicts —
motion the operator reads as noise because none of it needs an answer.

The fleet watcher already tiers its output: actionable deltas wake
immediately, routine churn rides the next wake. This module gives every
other wrapper the same shape. Progress lines accumulate in
:class:`ProgressDigest` and leave as ONE line per flush window, in
order, with nothing dropped; the immediate tier (urgent, summary,
metadata) flushes the buffer ahead of itself so a wake never arrives
without the motion that led to it. The raw capture is untouched: it
still holds every line exactly as the command printed it.

The window is one constant here, overridable per run by
``--flush-seconds`` on any wrapper. ``--flush-seconds 0`` turns batching
off and emits each progress line as it arrives.
"""

from __future__ import annotations

import argparse
import time
from typing import Callable, Optional, Sequence

#: Seconds between progress digests. Deliberately a constant and a flag
#: rather than a machine-config key: the window is a property of how a
#: run reads, and a per-run override is the only adjustment anyone has
#: needed.
DEFAULT_FLUSH_SECONDS = 120.0
#: Joins the buffered signals inside one digest line.
DIGEST_SEPARATOR = " · "

FLUSH_SECONDS_FLAG = "--flush-seconds"

FLUSH_SECONDS_HELP = (
    "Seconds between progress digests "
    f"(default {DEFAULT_FLUSH_SECONDS:g}). 0 emits every progress line as "
    "it arrives. Urgent lines are never delayed."
)

TIER_HELP = f"""\
wake tiers:
  Urgent lines — errors, denials, refusals, failure signatures, terminal
  outcomes, the relay-unavailable notice, and the exit sentinel — reach a
  follower the moment they arrive, carrying whatever progress was buffered
  before them.

  Progress lines — stage boundaries, run and workflow ids, rehearsal
  verdicts, percentages, status polls — are buffered and emitted as ONE
  `# watch_<kind> digest ...` line at most every {DEFAULT_FLUSH_SECONDS:g}
  seconds, and always at completion. Read a digest as one wake covering
  everything between the middle dots, and relay it as it stands.

  The raw capture keeps every line unchanged either way.
  `{FLUSH_SECONDS_FLAG} N` resizes the window for one run;
  `{FLUSH_SECONDS_FLAG} 0` restores one wake per progress line.
"""


def add_flush_seconds_argument(parser: argparse.ArgumentParser) -> None:
    """Register ``--flush-seconds`` so it appears in the wrapper's help."""
    parser.add_argument(
        FLUSH_SECONDS_FLAG,
        dest="flush_seconds",
        type=float,
        default=None,
        metavar="N",
        help=FLUSH_SECONDS_HELP,
    )


def attach_flush_seconds(parser: argparse.ArgumentParser) -> None:
    """Register the option and teach the two wake tiers, in one call.

    Every wrapper's ``--help`` names the same tiers because they all
    reach them through here rather than restating them per wrapper.
    """
    add_flush_seconds_argument(parser)
    parser.formatter_class = argparse.RawDescriptionHelpFormatter
    existing = (parser.epilog or "").rstrip()
    parser.epilog = f"{existing}\n\n{TIER_HELP}" if existing else TIER_HELP


def _parse_flush_seconds(raw: str) -> float:
    """Parse one ``--flush-seconds`` value, refusing anything unusable."""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise SystemExit(
            f"{FLUSH_SECONDS_FLAG} expects a number of seconds, got {raw!r}. "
            f"Use `{FLUSH_SECONDS_FLAG} 30` to resize the digest window, or "
            f"`{FLUSH_SECONDS_FLAG} 0` for one wake per progress line."
        ) from None
    if value < 0:
        raise SystemExit(
            f"{FLUSH_SECONDS_FLAG} cannot be negative (got {value:g}). "
            f"Use `{FLUSH_SECONDS_FLAG} 0` for one wake per progress line."
        )
    return value


def extract_flush_seconds(argv: Sequence[str]) -> tuple[list[str], Optional[float]]:
    """Pull ``--flush-seconds`` out of any position in *argv*.

    Wrappers collect their pass-through with ``nargs=REMAINDER``, so a
    flag typed after ``--`` would otherwise be handed to the watched
    command. Pre-extracting makes every position equivalent, exactly as
    ``--print-streaming-pair`` already is.
    """
    filtered: list[str] = []
    value: Optional[float] = None
    args = list(argv)
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == FLUSH_SECONDS_FLAG:
            if index + 1 >= len(args):
                raise SystemExit(
                    f"{FLUSH_SECONDS_FLAG} needs a value, for example "
                    f"`{FLUSH_SECONDS_FLAG} 30`."
                )
            value = _parse_flush_seconds(args[index + 1])
            index += 2
            continue
        if arg.startswith(f"{FLUSH_SECONDS_FLAG}="):
            value = _parse_flush_seconds(arg.split("=", 1)[1])
            index += 1
            continue
        filtered.append(arg)
        index += 1
    return filtered, value


def resolve_flush_seconds(
    namespace: object, extracted: Optional[float] = None
) -> float:
    """Return the effective window: the run's own flag, else the default."""
    value = extracted
    if value is None:
        value = getattr(namespace, "flush_seconds", None)
    return DEFAULT_FLUSH_SECONDS if value is None else value


def streaming_pair_options(flush_seconds: Optional[float]) -> list[str]:
    """Wrapper options a pasted background command must replay.

    A caller who resized the window while minting the pair means it for
    the run that pair starts, so the flag travels with it.
    """
    if flush_seconds is None:
        return []
    return [FLUSH_SECONDS_FLAG, f"{flush_seconds:g}"]


class ProgressDigest:
    """Accumulate progress signals and release them one line at a time.

    Created once per ``run_watcher`` invocation. ``add`` buffers a line
    and returns a digest when the window has elapsed; ``flush`` releases
    the buffer unconditionally, which is what an urgent line and the end
    of the run each do. With ``flush_seconds`` of 0 the digest is a
    pass-through and every line is returned as it arrives.
    """

    def __init__(
        self,
        *,
        kind: str,
        label: Optional[str] = None,
        flush_seconds: float = DEFAULT_FLUSH_SECONDS,
        time_source: Callable[[], float] = time.monotonic,
    ) -> None:
        self._kind = kind
        self._label = (label or "").strip()
        self._flush_seconds = max(0.0, flush_seconds)
        self._now = time_source
        self._signals: list[str] = []
        self._last_flush_at: Optional[float] = None

    @property
    def batching(self) -> bool:
        """False when the run asked for one wake per progress line."""
        return self._flush_seconds > 0

    def seconds_until_flush(self) -> Optional[float]:
        """Seconds until the buffer is due, or ``None`` when it is empty."""
        if not self._signals:
            return None
        if self._last_flush_at is None:
            return 0.0
        elapsed = self._now() - self._last_flush_at
        return max(0.0, self._flush_seconds - elapsed)

    def add(self, line: str) -> Optional[str]:
        """Buffer one progress line; return a line to emit when one is due."""
        if not self.batching:
            return line
        signal = line.strip()
        if signal:
            self._signals.append(signal)
        if self.seconds_until_flush() == 0.0:
            return self.flush()
        return None

    def flush(self) -> Optional[str]:
        """Return the buffered digest line, or ``None`` when nothing is held."""
        if not self._signals:
            return None
        signals = DIGEST_SEPARATOR.join(self._signals)
        self._signals.clear()
        self._last_flush_at = self._now()
        label = f" {self._label}" if self._label else ""
        return f"# watch_{self._kind} digest{label}: {signals}\n"


__all__ = [
    "DEFAULT_FLUSH_SECONDS",
    "DIGEST_SEPARATOR",
    "FLUSH_SECONDS_FLAG",
    "FLUSH_SECONDS_HELP",
    "ProgressDigest",
    "TIER_HELP",
    "add_flush_seconds_argument",
    "extract_flush_seconds",
    "resolve_flush_seconds",
    "streaming_pair_options",
]
