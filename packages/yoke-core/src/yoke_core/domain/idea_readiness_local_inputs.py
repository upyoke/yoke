"""What a readiness host asks for when it cannot read the item's files.

Four readiness checks read the item project's working tree. The hosted
API never has one, and it never will, so those checks came back
``unavailable`` for every relayed run even when the caller's own machine
had the project checked out the whole time.

This module is the outgoing half of the handoff.
:func:`build_local_execution_request` resolves everything those checks
need that is not a file — the spec, the planned-claim carve-outs, the
declared rehearsal commands — and names the item, project and spec
revision the answer will be held to. A machine with the checkout runs the
checks against that request (see
:mod:`yoke_core.engines.readiness_local_observations`) and answers.

The incoming half is :mod:`idea_readiness_observation_binding`, which
decides whether an answer may stand in for having run the checks here,
and states exactly which parts of it the control plane can verify.
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional, Tuple

from yoke_core.domain.idea_readiness_check_refs import (
    planned_claim_suppressed_refs,
)
from yoke_core.domain.idea_readiness_checkout import CHECKOUT_DEPENDENT_CHECKS
from yoke_core.domain.idea_readiness_results import Issue, UnavailableValidation


def spec_digest(spec_text: str) -> str:
    """The server-verified half of an answer's binding."""
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

    # Ahead of the claim probes: on a schema without the path-claim tables
    # those abort the transaction, and every read after them fails.
    item_ref = render_item_ref(conn, item_id)
    project_id, project_slug = item_project_identity(conn, item_id)
    commands, planned_paths = rehearsal_command_inputs(conn, item_id)
    return {
        "item_id": int(item_id),
        "item_ref": item_ref,
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


def checkout_absent_findings(
    conn: Any,
    item_id: int,
    spec_text: str,
    observations: Optional[Dict[str, Any]],
) -> Tuple[List[Issue], List[Dict[str, Any]], List[UnavailableValidation]]:
    """What the file-reading checks yield on a host without the tree.

    With an answer from a machine that has the checkout, that machine's
    findings — once the binding holds and every finding is one the checks
    could have produced. Without one, four unperformed checks.
    """
    from yoke_core.domain.attestation_rehearsal_dryrun import (
        rehearsal_command_inputs,
    )
    from yoke_core.domain.idea_readiness_checkout import (
        item_project_identity,
        unavailable_checkout_dependent_checks,
    )
    from yoke_core.domain.idea_readiness_observation_binding import (
        ObservationBinding,
        findings_from_observations,
    )
    from yoke_core.domain.project_identity import render_item_ref

    if observations is None:
        return ([], [], unavailable_checkout_dependent_checks(conn, item_id))
    item_ref = render_item_ref(conn, item_id)
    project_id, _slug = item_project_identity(conn, item_id)
    commands, _planned = rehearsal_command_inputs(conn, item_id)
    return findings_from_observations(
        observations,
        ObservationBinding(
            item_id=int(item_id), project_id=project_id, spec_text=spec_text,
        ),
        item_ref=item_ref,
        rehearsal_commands=commands,
    )


__all__ = [
    "build_local_execution_request",
    "checkout_absent_findings",
    "read_spec",
    "spec_digest",
]
