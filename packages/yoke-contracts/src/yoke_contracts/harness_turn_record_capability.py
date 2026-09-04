"""Whether a harness leaves a turn record a machine can read back.

A **turn record** is the native's own durable account of how its last turn
ended, written by the harness rather than by Yoke. It matters for exactly
one question: a turn that ends without firing its turn-end hook tells the
control plane nothing, so its posture stays ``running`` forever and every
wake for it resolves an operation its surface does not support. The record
is the only remaining evidence that the turn is over.

Most harnesses need no record, and that is a capability fact rather than an
omission: a harness whose turn end always fires its hook reports itself, so
nothing is ever stuck for it and opening a transcript would buy nothing.
Saying that out loud is the point of this contract — a harness with no
reader must declare *why* it needs none, so a real gap can never hide behind
the same silence as a designed deferral.

This module is the single source for those facts. The renderer copies each
entry into ``runtime/harness/<harness_id>/manifest.json`` under
``turn_record`` (see ``runtime/harness/manifest-schema.md``), and
:func:`turn_record_surfaces` derives the surface set the probe path reads,
so no caller keeps its own list of which harnesses have a record.

Each entry carries the evidence that established it. ``unverified`` is a
first-class value — a harness nobody has probed says so, rather than
inheriting a neighbour's answer.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal


# ``readable`` / ``none`` are measured answers; ``unverified`` means no probe
# has been run and no claim may be made from this contract.
TurnRecordClass = Literal["readable", "none", "unverified"]


@dataclass(frozen=True)
class HarnessTurnRecordCapability:
    """One harness family's turn-record facts plus the evidence behind them."""

    turn_record: TurnRecordClass
    turn_record_mechanism: str
    #: The surface the probe was verified on, and the only surface whose
    #: sessions a reader is derived for. A family's other surfaces may write
    #: the same file, but nothing here claims a record it has not read.
    verified_on_surface: str
    evidence: str

    def to_json(self) -> dict[str, object]:
        return asdict(self)


HARNESS_TURN_RECORD_CAPABILITIES: dict[str, HarnessTurnRecordCapability] = {
    "claude-code": HarnessTurnRecordCapability(
        turn_record="none",
        turn_record_mechanism="",
        verified_on_surface="claude-cli",
        evidence=(
            "No reader is needed and none is built. Claude fires its "
            "turn-end hook on every ending observed so far, including "
            "failures, so posture is stamped by the hook runner and no wake "
            "is left resolving an unsupported operation. A record would be "
            "read to answer a question the hook has already answered. "
            "Designed deferral: if a Claude ending is ever observed that "
            "fires no hook, this entry becomes the gap to close."
        ),
    ),
    "codex": HarnessTurnRecordCapability(
        turn_record="readable",
        turn_record_mechanism=(
            "rollout tail: the last JSON line of "
            "~/.codex/sessions/YYYY/MM/DD/rollout-<started>-<session_id>"
            ".jsonl is a task_complete event, carrying an error payload "
            "when the turn ended on a vendor failure"
        ),
        verified_on_surface="codex-cli",
        evidence=(
            "Observed live twice. A turn ending on 'Selected model is at "
            "capacity' left the CLI process at its prompt and fired no Stop "
            "hook, and on 2026-09-03 five workers ended on an upstream 404 "
            "from the responses endpoint the same way. In both cases the "
            "session's last hook event predated the ending and the rollout "
            "tail was the only record that the turn was over."
        ),
    ),
    "cursor": HarnessTurnRecordCapability(
        turn_record="none",
        turn_record_mechanism="",
        verified_on_surface="cursor-cli",
        evidence=(
            "No reader is needed and none is built. Cursor fires its "
            "turn-end hook on every ending observed so far, so the same "
            "reasoning as claude-code applies: the hook stamps posture and "
            "a transcript read would answer nothing further. Designed "
            "deferral on the same terms."
        ),
    ),
}


def turn_record_capability_for_harness(
    harness_id: str | None,
) -> HarnessTurnRecordCapability:
    """Return one harness family's turn-record facts.

    An unknown harness id resolves to ``unverified`` rather than a guess, so
    a newly onboarded adapter reads as "nobody has probed this" until
    someone adds its measured entry above. ``unverified`` is deliberately
    not ``none``: a harness nobody has looked at is not a harness known to
    need no reader, and treating the two alike is how a real gap would hide.
    """
    known = HARNESS_TURN_RECORD_CAPABILITIES.get(str(harness_id or ""))
    if known is not None:
        return known
    return HarnessTurnRecordCapability(
        turn_record="unverified",
        turn_record_mechanism="",
        verified_on_surface="",
        evidence=(
            f"No turn-record probe recorded for harness id {harness_id!r}. "
            "Add a measured entry to yoke_contracts."
            "harness_turn_record_capability."
            "HARNESS_TURN_RECORD_CAPABILITIES before any surface states "
            "whether this harness leaves a readable turn record."
        ),
    )


def turn_record_surfaces() -> tuple[str, ...]:
    """Surfaces whose harness declares a readable turn record.

    The probe path reads this rather than naming surfaces itself, so
    onboarding a harness with a record is one capability entry plus its
    reader, and a harness without one contributes nothing by construction.
    """
    return tuple(
        sorted(
            capability.verified_on_surface
            for capability in HARNESS_TURN_RECORD_CAPABILITIES.values()
            if capability.turn_record == "readable" and capability.verified_on_surface
        )
    )


__all__ = (
    "HARNESS_TURN_RECORD_CAPABILITIES",
    "HarnessTurnRecordCapability",
    "TurnRecordClass",
    "turn_record_capability_for_harness",
    "turn_record_surfaces",
)
