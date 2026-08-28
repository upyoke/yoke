"""Name the sessions a broker decision considered, and why each was refused.

A not-ready decision that says only "no claim-free pair" leaves the next
operator to re-derive, by hand and against a roster that has moved on, which
of the declared axes actually failed — and it cannot distinguish "no candidate
existed" from "candidates existed and every one was ineligible" from "the pair
this run just prepared ended before the re-read". Those three want three
different next actions, so the decision carries the evidence that separates
them.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from runtime.api.tools.session_control_live_acceptance_broker_eligibility import (
    BrokerBinding,
    broker_session_eligibility,
)


#: Eligibility codes that mean the session is not there to be woken — it ended,
#: was terminated, or never registered. Preparation reads these to tell "the
#: pair I just made is gone" apart from "the pair I just made is ineligible".
ABSENT_SESSION_CODES = frozenset(
    {
        "registration_missing",
        "broker_registration_missing",
        "registration_not_active",
        "broker_not_active",
    }
)


def _session_id(row: Mapping[str, Any] | None) -> str:
    return str((row or {}).get("session_id") or "").strip()


def candidate_evidence(
    binding: BrokerBinding,
    *,
    project: str,
    surface: str,
    advertised_version: str,
    target: Mapping[str, Any] | None,
    peer: Mapping[str, Any] | None,
    candidates: Sequence[Mapping[str, Any]] = (),
) -> tuple[dict[str, Any], ...]:
    """One row per considered session: the failing axis per role, or ``None``.

    A ``None`` failure means the session is eligible for that role. Rows are
    ordered by session id so two reads of the same roster compare cleanly.
    """
    rows: dict[str, Mapping[str, Any]] = {}
    for row in (target, peer, *candidates):
        session_id = _session_id(row)
        if session_id and row is not None:
            rows.setdefault(session_id, row)
    evidence: list[dict[str, Any]] = []
    for session_id in sorted(rows):
        row = rows[session_id]
        evidence.append(
            {
                "session_id": session_id,
                "bound_role": (
                    "target"
                    if session_id == binding.target_session_id
                    else "peer"
                    if session_id == binding.peer_session_id
                    else None
                ),
                "target_failure": broker_session_eligibility(
                    row,
                    project=project,
                    surface=surface,
                    advertised_version=advertised_version,
                    machine_id=binding.machine_id,
                    role="target",
                ),
                "peer_failure": broker_session_eligibility(
                    row,
                    project=project,
                    surface=surface,
                    advertised_version=advertised_version,
                    machine_id=binding.machine_id,
                    role="peer",
                ),
            }
        )
    return tuple(evidence)


def sessions_absent(
    evidence: Sequence[Mapping[str, Any]],
    session_ids: Sequence[str],
) -> tuple[str, ...]:
    """Return which of ``session_ids`` the evidence reports as not there.

    A session missing from the evidence entirely is absent too: the roster read
    that produced the evidence did not see it at all.
    """
    seen = {str(row.get("session_id") or ""): row for row in evidence}
    absent: list[str] = []
    for session_id in session_ids:
        row = seen.get(session_id)
        if row is None:
            absent.append(session_id)
            continue
        codes = {row.get("target_failure"), row.get("peer_failure")} - {None}
        if codes and codes <= ABSENT_SESSION_CODES:
            absent.append(session_id)
    return tuple(absent)


__all__ = ["ABSENT_SESSION_CODES", "candidate_evidence", "sessions_absent"]
