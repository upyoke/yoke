"""Whether a harness can run several sub-agents at once, and by which primitive.

Conduct fans an epic out to one Engineer per ready lane. That fan-out is only
concurrent when the harness can run several sub-agents in parallel and hand
each result back as it finishes; without that, the same dispatch runs one
sub-agent at a time. This module is the single source for that fact. The
renderer copies each entry into ``runtime/harness/<harness_id>/manifest.json``
under ``parallel_subagents`` (documented in
``runtime/harness/manifest-parallel-subagents.md``), and Conduct reads the
manifest field before it dispatches.

``unverified`` is a first-class value: a harness nobody has observed running
sub-agents concurrently says so, and Conduct dispatches serially there with a
recorded deferral rather than assuming a neighbour's answer.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal


# ``supported`` / ``none`` are observed answers; ``unverified`` means nobody
# has observed the harness either way.
ParallelClass = Literal["supported", "none", "unverified"]


@dataclass(frozen=True)
class HarnessSubagentCapability:
    """One harness family's parallel sub-agent fact plus its evidence."""

    parallel_subagents: ParallelClass
    mechanism: str
    verified_on_surface: str
    evidence: str

    def to_json(self) -> dict[str, object]:
        return asdict(self)


HARNESS_SUBAGENT_CAPABILITIES: dict[str, HarnessSubagentCapability] = {
    "claude-code": HarnessSubagentCapability(
        parallel_subagents="supported",
        mechanism="Agent",
        verified_on_surface="claude-cli",
        evidence=(
            "Several Agent tool calls sent in one message run concurrently, "
            "and each sub-agent's completion arrives as its own notification, "
            "so the parent can act on one result while others still run."
        ),
    ),
    "codex": HarnessSubagentCapability(
        parallel_subagents="supported",
        mechanism="custom agents (.codex/agents/yoke-<role>.toml)",
        verified_on_surface="codex-cli",
        evidence=(
            "Observed 2026-10-16: a codex-cli Conduct session ran an epic's "
            "task Engineers concurrently across lanes."
        ),
    ),
    "cursor": HarnessSubagentCapability(
        parallel_subagents="unverified",
        mechanism="",
        verified_on_surface="",
        evidence=(
            "Cursor dispatches named sub-agents through its Task tool, but no "
            "session has been observed running several at once. Conduct "
            "dispatches one sub-agent at a time here and records that "
            "deferral until a probe adds a measured entry."
        ),
    ),
}


def subagent_capability_for_harness(
    harness_id: str | None,
) -> HarnessSubagentCapability:
    """Return one harness family's parallel sub-agent fact.

    An unknown harness id resolves to ``unverified`` rather than a guess.
    """
    known = HARNESS_SUBAGENT_CAPABILITIES.get(str(harness_id or ""))
    if known is not None:
        return known
    return HarnessSubagentCapability(
        parallel_subagents="unverified",
        mechanism="",
        verified_on_surface="",
        evidence=(
            f"No parallel sub-agent observation recorded for harness id "
            f"{harness_id!r}. Add a measured entry to "
            "yoke_contracts.harness_subagent_capability."
            "HARNESS_SUBAGENT_CAPABILITIES before any surface relies on it."
        ),
    )


__all__ = (
    "HARNESS_SUBAGENT_CAPABILITIES",
    "HarnessSubagentCapability",
    "ParallelClass",
    "subagent_capability_for_harness",
)
