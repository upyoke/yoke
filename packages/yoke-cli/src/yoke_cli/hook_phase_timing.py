"""Split one hook invocation's wall time into the phases that explain it.

A hook that took four seconds is not a diagnosis. The question is always
which phase paid for it: waiting on the machine-local resident over its
socket, evaluating the canonical in-process fallback after the resident
could not answer, or something outside both. These three are reported
together with the reason the fallback ran, because a slow hook whose
resident wait dominates and a slow hook whose evaluation dominates need
opposite repairs.

A phase that was not measured is reported as ``not-measured`` rather than
zero: a zero here reads as "instant" and would quietly hide a gap in
coverage. Only durations and a refusal code are ever printed — never the
tool payload, the environment, or a credential — and rendering is pure
string work, so the report cannot delay or fail the tool call.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, Optional


PHASE_TIMING_ENV_VAR = "YOKE_HOOK_PHASE_TIMING"
PHASE_TIMING_MARKER = "YOKE_HOOK_PHASE_TIMING"
_UNMEASURED = "not-measured"


def phase_timing_requested(env: Optional[Mapping[str, str]] = None) -> bool:
    """True when this machine asked for the timing line on every hook."""
    source = os.environ if env is None else env
    return source.get(PHASE_TIMING_ENV_VAR, "").strip().lower() in {"1", "true", "yes"}


@dataclass(frozen=True)
class HookPhaseTiming:
    """One invocation's phase durations, in milliseconds.

    ``resident_wait_ms`` covers connect attempts, restart handshakes, and
    the response wait — everything spent on the shared helper. ``fallback_ms``
    covers the canonical in-process evaluation, including any synchronous
    telemetry reporting it performs on completion. ``client_wall_ms`` is the
    hook process end to end, so it is the only figure comparable with an
    operator's stopwatch.
    """

    resident_wait_ms: Optional[int] = None
    fallback_ms: Optional[int] = None
    client_wall_ms: Optional[int] = None
    fallback_reason: str = ""

    def summary(self) -> str:
        fields = [
            f"resident_wait_ms={_render(self.resident_wait_ms)}",
            f"fallback_ms={_render(self.fallback_ms)}",
            f"client_wall_ms={_render(self.client_wall_ms)}",
            f"fallback_reason={self.fallback_reason or 'none'}",
        ]
        return f"{PHASE_TIMING_MARKER}: " + " ".join(fields)


def _render(value: Optional[int]) -> str:
    return _UNMEASURED if value is None else str(max(0, int(value)))


__all__ = [
    "HookPhaseTiming",
    "PHASE_TIMING_ENV_VAR",
    "PHASE_TIMING_MARKER",
    "phase_timing_requested",
]
