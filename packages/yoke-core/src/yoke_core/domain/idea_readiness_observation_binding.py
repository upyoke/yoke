"""Deciding whether an answer from another machine describes this run.

:mod:`idea_readiness_local_inputs` publishes what the file-reading checks
need; a machine holding the checkout answers. This module decides whether
that answer may stand in for having run them here, and it is the only
place that decision is made.

What is actually proven, stated plainly, because the difference matters:

* The **spec digest** is server-verified. The control plane hashes the
  spec it holds right now and compares, so an answer that read a
  different revision cannot pass as one that read this one.
* The **item and project** are server-verified the same way, against the
  item this run is about. Two items can hold identical spec text, so the
  digest alone would let an answer about one stand in for the other.
* The **checkout revision is not verified and cannot be.** The control
  plane has no checkout; the revision is the observing machine's own
  self-report. It is kept because it catches the honest race this
  handoff invites — a tree edited while the checks were mid-read, which
  the machine detects by reading the revision on both sides of the run —
  and it is worth nothing against a machine that lies. Treat every
  file-derived finding here as trusted exactly as far as that machine is.

Every mismatch resolves the same way: the checks stay unperformed. Not a
pass, not a failure, with the reason named. That includes a finding the
admission policy would not accept, which fails closed rather than being
dropped quietly — a silently discarded finding is a real defect reported
as a pass, and version skew is the likeliest way to get one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

from yoke_core.domain.idea_readiness_checkout import CHECKOUT_DEPENDENT_CHECKS
from yoke_core.domain.idea_readiness_results import Issue, UnavailableValidation

STALE_SPEC_REASON = "local_observations_stale_spec"
MOVED_CHECKOUT_REASON = "local_observations_checkout_moved"
UNVERIFIABLE_REVISION_REASON = "local_observations_unverifiable_revision"
INCOMPLETE_REASON = "local_observations_incomplete"
WRONG_ITEM_REASON = "local_observations_wrong_item"
UNRECOGNIZED_CHECK_REASON = "local_observations_unrecognized_check"
UNADMISSIBLE_FINDING_REASON = "local_observations_unadmissible_finding"


@dataclass(frozen=True)
class ObservationBinding:
    """The control plane's own facts, against which an answer is checked."""

    item_id: int
    project_id: Optional[int]
    spec_text: str


def _digest(spec_text: str) -> str:
    from yoke_core.domain.idea_readiness_local_inputs import spec_digest

    return spec_digest(spec_text)


def binding_mismatch_reason(
    observations: Any, binding: ObservationBinding,
) -> str:
    """Name why an answer cannot stand in for this run, or ``""`` when it can."""
    if not isinstance(observations, dict):
        return INCOMPLETE_REASON
    if str(observations.get("spec_sha256") or "") != _digest(binding.spec_text):
        return STALE_SPEC_REASON
    if int(observations.get("item_id") or 0) != int(binding.item_id):
        return WRONG_ITEM_REASON
    if binding.project_id is not None and (
        int(observations.get("project_id") or 0) != int(binding.project_id)
    ):
        return WRONG_ITEM_REASON
    if not str(observations.get("checkout_revision") or ""):
        return UNVERIFIABLE_REVISION_REASON
    if observations.get("checkout_moved"):
        return MOVED_CHECKOUT_REASON
    return _reported_check_mismatch(observations)


def _reported_check_mismatch(observations: Dict[str, Any]) -> str:
    """The reported checks must be exactly the ones this host asked for.

    The server never adopts this list as its record of what ran — that is
    always :data:`CHECKOUT_DEPENDENT_CHECKS`. The list is read only to
    catch skew: fewer names means a check went unperformed, and a name
    this host never asked for means the two sides disagree about what the
    handoff covers, which is not something to resolve by guessing.
    """
    expected = set(CHECKOUT_DEPENDENT_CHECKS)
    reported = {str(check) for check in (observations.get("checks") or ())}
    if reported - expected:
        return UNRECOGNIZED_CHECK_REASON
    if expected - reported:
        return INCOMPLETE_REASON
    return ""


def findings_from_observations(
    observations: Any,
    binding: ObservationBinding,
    *,
    item_ref: str,
    rehearsal_commands: Iterable[str] = (),
) -> Tuple[List[Issue], List[Dict[str, Any]], List[UnavailableValidation]]:
    """Adopt an answer's findings, or report every check still unperformed."""
    from yoke_core.domain.idea_readiness_observation_admission import (
        admit_advisories,
        admit_issues,
    )

    reason = binding_mismatch_reason(observations, binding)
    if reason:
        return ([], [], unbound_observations(reason, item_ref))
    issues, rejected = admit_issues(
        observations.get("issues"),
        spec_text=binding.spec_text,
        rehearsal_commands=rehearsal_commands,
    )
    if rejected:
        return ([], [], unbound_observations(
            UNADMISSIBLE_FINDING_REASON, item_ref, context={"rejected": rejected},
        ))
    advisories = admit_advisories(
        observations.get("advisories"), spec_text=binding.spec_text,
    )
    return (issues, advisories, [])


def unbound_observations(
    reason: str,
    item_ref: str,
    *,
    context: Optional[Dict[str, Any]] = None,
) -> List[UnavailableValidation]:
    """Report every file-reading check unperformed, naming the mismatch."""
    return [
        UnavailableValidation(
            check=check,
            reason=reason,
            recovery=_RECOVERY[reason].format(check=check, item=item_ref),
            retryable=True,
            context=dict(context or {}),
        )
        for check in CHECKOUT_DEPENDENT_CHECKS
    ]


_RECOVERY = {
    STALE_SPEC_REASON: (
        "{check} read a spec revision the control plane no longer holds — "
        "{item} changed while the check was running, so its answer cannot "
        "be trusted. Re-run readiness against the current spec."
    ),
    MOVED_CHECKOUT_REASON: (
        "{check} reads files, and the checkout it read moved while it was "
        "reading — the result describes no single revision of {item}'s "
        "project. Let the tree settle and re-run readiness."
    ),
    UNVERIFIABLE_REVISION_REASON: (
        "{check} ran against a checkout whose revision could not be read, "
        "so nothing shows whether the tree held still for {item}. Make `git "
        "rev-parse HEAD` and `git status --porcelain` answer in that "
        "checkout, then re-run readiness."
    ),
    INCOMPLETE_REASON: (
        "{check} was not among the checks the machine holding the checkout "
        "reported for {item}, so it went unperformed. Re-run readiness from "
        "a machine whose checkout for that project is registered."
    ),
    WRONG_ITEM_REASON: (
        "{check} was reported for a different item or project than {item}, "
        "so it says nothing about this one. Re-run readiness for {item} "
        "from a machine whose checkout for its project is registered."
    ),
    UNRECOGNIZED_CHECK_REASON: (
        "the machine holding {item}'s checkout reported a check this host "
        "never asked for, so the two sides disagree about what the handoff "
        "covers and {check} cannot be taken as performed. Bring that "
        "machine's Yoke build to the one this host is serving."
    ),
    UNADMISSIBLE_FINDING_REASON: (
        "the machine holding {item}'s checkout reported a finding the "
        "file-reading checks cannot produce, so {check} cannot be taken as "
        "performed — treating the rest as complete could report a real "
        "defect as a pass. Bring that machine's Yoke build to the one this "
        "host is serving."
    ),
}


__all__ = [
    "INCOMPLETE_REASON",
    "MOVED_CHECKOUT_REASON",
    "ObservationBinding",
    "STALE_SPEC_REASON",
    "UNADMISSIBLE_FINDING_REASON",
    "UNRECOGNIZED_CHECK_REASON",
    "UNVERIFIABLE_REVISION_REASON",
    "WRONG_ITEM_REASON",
    "binding_mismatch_reason",
    "findings_from_observations",
    "unbound_observations",
]
