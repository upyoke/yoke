"""Report a pytest run's wall clock beside pytest's own reported duration.

pytest times only its session. Everything outside that timer — test-cluster
preparation, xdist worker startup, anything blocking before the session clock
starts — is invisible in the summary line operators actually read. A suite
whose wall clock ran four times its self-report went unnoticed for a day and
a half for exactly that reason, so the wrapper reports both numbers and says
when they disagree enough to be worth investigating.

Split from :mod:`watch_pytest` to keep that module inside the authored-file
line limit.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


# Flag only when the gap is both proportionally large AND absolutely worth an
# operator's attention. Short runs routinely spend more time spinning up xdist
# workers than running tests; flagging those would train readers to ignore the
# line, which is the failure this reporting exists to prevent.
DIVERGENCE_FACTOR = 1.5
DIVERGENCE_FLOOR_S = 60.0

# pytest's summary tail, e.g. "20047 passed, 15 skipped in 404.69s (0:06:44)".
_SESSION_DURATION = re.compile(r" in (\d+(?:\.\d+)?)s(?: \(|\s|$)")


def reported_session_seconds(raw_capture: str) -> "float | None":
    """Return pytest's self-reported duration from its summary line.

    ``None`` when the capture is unreadable or carries no summary — an
    interrupted or crashed run still deserves a wall-clock number, just
    without a comparison.
    """
    try:
        text = Path(raw_capture).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    matches = _SESSION_DURATION.findall(text)
    if not matches:
        return None
    try:
        # Warning summaries and reruns can print earlier durations; the
        # session total is the last one.
        return float(matches[-1])
    except ValueError:
        return None


def report(wall_seconds: float, raw_capture: str) -> None:
    """Print wall clock, pytest's figure when known, and any wide gap."""
    line = f"# watch_pytest wall-clock: {wall_seconds:.1f}s"
    reported = reported_session_seconds(raw_capture)
    if reported is not None:
        line += f" (pytest self-reported {reported:.1f}s)"
        gap = wall_seconds - reported
        if wall_seconds > reported * DIVERGENCE_FACTOR and gap >= DIVERGENCE_FLOOR_S:
            line += (
                f" -- {gap:.0f}s spent OUTSIDE pytest's timer; check "
                f"test-cluster preparation and xdist worker startup"
            )
    sys.stderr.write(line + "\n")


__all__ = [
    "DIVERGENCE_FACTOR",
    "DIVERGENCE_FLOOR_S",
    "report",
    "reported_session_seconds",
]
