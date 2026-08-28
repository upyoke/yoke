"""Whether a harness can resume an idle model turn, and by which primitive.

An **idle wake** is an out-of-band signal that resumes a model turn *after*
that turn has already ended — the property that decides whether a session can
arm a background watcher and be woken per match, or must instead keep the
turn alive and poll. A **timer wake** is the same resumption scheduled by the
session itself for a future time.

This module is the single source for those facts. The renderer copies each
entry into ``runtime/harness/<harness_id>/manifest.json`` under ``agent_wake``
(see ``runtime/harness/manifest-schema.md``), and
``yoke_core.tools.render_harness_capability_inline`` renders the same entries
into every teaching surface that shows capability text to a reader. Prose
never states one of these facts on its own authority: change the entry here,
re-render, and every surface follows.

Each entry carries the evidence that established it, because an unevidenced
capability claim is what this contract exists to replace. ``unverified`` is a
first-class value — a harness nobody has probed says so, rather than
inheriting a neighbour's answer.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal


# ``supported`` / ``none`` are measured answers; ``unverified`` means no probe
# has been run and no claim may be made from this contract.
WakeClass = Literal["supported", "none", "unverified"]


@dataclass(frozen=True)
class HarnessWakeCapability:
    """One harness family's wake facts plus the evidence behind them."""

    idle_wake: WakeClass
    idle_wake_mechanism: str
    timer_wake: WakeClass
    timer_wake_mechanism: str
    verified_on_surface: str
    evidence: str

    def to_json(self) -> dict[str, object]:
        return asdict(self)


HARNESS_WAKE_CAPABILITIES: dict[str, HarnessWakeCapability] = {
    "claude-code": HarnessWakeCapability(
        idle_wake="supported",
        idle_wake_mechanism="Monitor",
        timer_wake="supported",
        timer_wake_mechanism="ScheduleWakeup",
        verified_on_surface="claude-cli",
        evidence=(
            "Monitor and ScheduleWakeup are first-class model-facing tools. "
            "Every stdout line a Monitor filter matches resumes the turn, "
            "which is what the main-session long-command rule is built on."
        ),
    ),
    "codex": HarnessWakeCapability(
        idle_wake="none",
        idle_wake_mechanism="",
        timer_wake="none",
        timer_wake_mechanism="",
        verified_on_surface="codex-cli",
        evidence=(
            "Live probe: foreground exec_command/PTY output streams only "
            "while the turn stays active; backgrounding with (...) & returns "
            "a prompt but stdout does not resume the model; a detached nohup "
            "child vanished when its command invocation ended and wrote zero "
            "lines. Continuations are an exec_command session_id plus "
            "explicit write_stdin polling; none resumes a turn after it ends."
        ),
    ),
    "cursor": HarnessWakeCapability(
        idle_wake="supported",
        idle_wake_mechanism="notify_on_output",
        timer_wake="none",
        timer_wake_mechanism="",
        verified_on_surface="cursor-cli",
        evidence=(
            "Live probe: the session ends its turn after a Shell call with "
            "block_until_ms=0 and a notify_on_output pattern, then receives "
            "system_notification pattern matches while idle — a working "
            "equivalent of Claude's Monitor. No timer wake was observed."
        ),
    ),
}


def wake_capability_for_harness(harness_id: str | None) -> HarnessWakeCapability:
    """Return one harness family's wake facts.

    An unknown harness id resolves to a fully ``unverified`` entry rather than
    a guess, so a newly onboarded adapter reads as "nobody has probed this"
    until someone adds its measured entry above.
    """
    known = HARNESS_WAKE_CAPABILITIES.get(str(harness_id or ""))
    if known is not None:
        return known
    return HarnessWakeCapability(
        idle_wake="unverified",
        idle_wake_mechanism="",
        timer_wake="unverified",
        timer_wake_mechanism="",
        verified_on_surface="",
        evidence=(
            f"No wake probe recorded for harness id {harness_id!r}. Add a "
            "measured entry to "
            "yoke_contracts.harness_wake_capability.HARNESS_WAKE_CAPABILITIES "
            "before any surface states what this harness can do."
        ),
    )


__all__ = (
    "WakeClass",
    "HarnessWakeCapability",
    "HARNESS_WAKE_CAPABILITIES",
    "wake_capability_for_harness",
)
