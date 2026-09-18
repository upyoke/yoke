"""The contract between a readiness host and the host holding the files.

Four readiness checks read the item project's working tree. The hosted
API never has one, and it never will, so those checks came back
``unavailable`` for every relayed run even when the caller's own machine
had the project checked out the whole time.

This module is the handoff. :func:`build_local_execution_request` resolves
everything those checks need from the control plane — the spec, the
planned-claim carve-outs, the declared rehearsal commands — and names the
spec revision it read. A machine with the checkout runs the checks against
that request (see :mod:`yoke_core.engines.readiness_local_observations`)
and returns observations. :func:`findings_from_observations` merges them
back, but only after :func:`binding_mismatch_reason` proves the
observations describe the spec the control plane holds right now and a
tree that did not move underneath them. A mismatch is not a pass and not
a failure: the checks stay unperformed, naming the concurrent change.
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional, Tuple

from yoke_core.domain.idea_readiness_check_refs import (
    planned_claim_suppressed_refs,
)
from yoke_core.domain.idea_readiness_checkout import CHECKOUT_DEPENDENT_CHECKS
from yoke_core.domain.idea_readiness_results import Issue, UnavailableValidation

STALE_SPEC_REASON = "local_observations_stale_spec"
MOVED_CHECKOUT_REASON = "local_observations_checkout_moved"
UNVERIFIABLE_REVISION_REASON = "local_observations_unverifiable_revision"
INCOMPLETE_REASON = "local_observations_incomplete"


def spec_digest(spec_text: str) -> str:
    """The revision marker observations are bound to."""
    return hashlib.sha256((spec_text or "").encode("utf-8")).hexdigest()


def read_spec(conn: Any, item_id: int) -> str:
    """The spec text every readiness check reads, as the control plane holds it."""
    from yoke_core.domain import db_backend

    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        f"SELECT spec FROM items WHERE id = {p}", (item_id,),
    ).fetchone()
    if row is None or row[0] is None:
        return ""
    return str(row[0])


def build_local_execution_request(
    conn: Any, item_id: int, spec_text: str,
) -> Dict[str, Any]:
    """Describe the file-reading checks a host without the tree skipped.

    Everything here is control-plane state the executing machine cannot
    read for itself: it relays to the control plane, it does not connect
    to one.
    """
    from yoke_core.domain.attestation_rehearsal_dryrun import (
        rehearsal_command_inputs,
    )
    from yoke_core.domain.idea_readiness_checkout import item_project_identity
    from yoke_core.domain.project_identity import render_item_ref

    commands, planned_paths = rehearsal_command_inputs(conn, item_id)
    project_id, project_slug = item_project_identity(conn, item_id)
    return {
        "item_id": int(item_id),
        "item_ref": render_item_ref(conn, item_id),
        "project_id": project_id,
        "project_slug": project_slug,
        "spec_sha256": spec_digest(spec_text),
        "spec_text": spec_text,
        "checks": list(CHECKOUT_DEPENDENT_CHECKS),
        "suppressed_refs": sorted(
            planned_claim_suppressed_refs(spec_text, conn, item_id)
        ),
        "rehearsal_commands": commands,
        "rehearsal_planned_paths": sorted(planned_paths),
    }


def binding_mismatch_reason(
    observations: Dict[str, Any], spec_text: str,
) -> str:
    """Name why observations cannot be trusted, or ``""`` when they can.

    Two concurrent changes can make a stale observation read as a pass:
    the item's spec being rewritten between the request and the answer,
    and the checkout moving while the checks were reading it. Both are
    caught here rather than by the checks, which see only one tree at one
    moment. A revision the observing machine could not establish at all
    is a third, and is refused for the same reason.
    """
    if not isinstance(observations, dict):
        return INCOMPLETE_REASON
    if str(observations.get("spec_sha256") or "") != spec_digest(spec_text):
        return STALE_SPEC_REASON
    if not str(observations.get("checkout_revision") or ""):
        return UNVERIFIABLE_REVISION_REASON
    if observations.get("checkout_moved"):
        return MOVED_CHECKOUT_REASON
    performed = {str(check) for check in (observations.get("checks") or [])}
    if not set(CHECKOUT_DEPENDENT_CHECKS) <= performed:
        return INCOMPLETE_REASON
    return ""


def checkout_absent_findings(
    conn: Any,
    item_id: int,
    spec_text: str,
    observations: Optional[Dict[str, Any]],
) -> Tuple[List[Issue], List[Dict[str, Any]], List[UnavailableValidation]]:
    """What the file-reading checks yield on a host without the tree.

    With observations from a machine that has the checkout, that machine's
    findings — once their binding holds. Without them, four unperformed
    checks.
    """
    from yoke_core.domain.idea_readiness_checkout import (
        unavailable_checkout_dependent_checks,
    )
    from yoke_core.domain.project_identity import render_item_ref

    if observations is None:
        return ([], [], unavailable_checkout_dependent_checks(conn, item_id))
    return findings_from_observations(
        observations, spec_text, item_ref=render_item_ref(conn, item_id),
    )


def findings_from_observations(
    observations: Dict[str, Any],
    spec_text: str,
    *,
    item_ref: str,
) -> Tuple[List[Issue], List[Dict[str, Any]], List[UnavailableValidation]]:
    """Merge observations, or report every check still unperformed."""
    reason = binding_mismatch_reason(observations, spec_text)
    if reason:
        return ([], [], unbound_observations(reason, item_ref))
    issues = [
        Issue(
            code=str(payload.get("code") or ""),
            message=str(payload.get("message") or ""),
            remediation=str(payload.get("remediation") or ""),
            context=dict(payload.get("context") or {}),
        )
        for payload in (observations.get("issues") or [])
    ]
    advisories = [dict(a) for a in (observations.get("advisories") or [])]
    return (issues, advisories, [])


def unbound_observations(
    reason: str, item_ref: str,
) -> List[UnavailableValidation]:
    """Report every file-reading check unperformed, naming the mismatch."""
    return [
        UnavailableValidation(
            check=check,
            reason=reason,
            recovery=_RECOVERY[reason].format(check=check, item=item_ref),
            retryable=True,
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
        "so nothing proves the tree held still for {item}. Make `git "
        "rev-parse HEAD` and `git status --porcelain` answer in that "
        "checkout, then re-run readiness."
    ),
    INCOMPLETE_REASON: (
        "{check} was not among the checks the machine holding the checkout "
        "reported for {item}, so it went unperformed. Re-run readiness from "
        "a machine whose checkout for that project is registered."
    ),
}


__all__ = [
    "INCOMPLETE_REASON",
    "MOVED_CHECKOUT_REASON",
    "STALE_SPEC_REASON",
    "UNVERIFIABLE_REVISION_REASON",
    "binding_mismatch_reason",
    "build_local_execution_request",
    "checkout_absent_findings",
    "findings_from_observations",
    "spec_digest",
    "unbound_observations",
]
