"""One central rule for which steering scope covers which work.

A steering seat is addressed as a role rather than as a session id, so
something has to decide which live seat a role-addressed message belongs
to. That decision is this rule and nothing else. It is deliberately not a
stored column: the answer changes the moment a seat is taken or released,
and a precomputed copy would be stale exactly during the handoff the role
addressing exists to survive.

A steering claim is scoped ``{"project_id": N}`` for a whole project, or
``{"project_id": N, "document": "SLUG"}`` for one strategy document inside
it. The scope object is validated by
:mod:`yoke_core.domain.work_claim_scope_shape`, so a further refinement --
an epic, a path domain, a workflow, an environment -- is another key in
that same object. Adding one is a validator change plus a coverage-target
change where the addressed work is described, never a schema change.

Which items a document scope covers is not this module's decision: the
addressed work arrives already described, and
:mod:`yoke_core.domain.steering_scope_membership` is what turns an item
into the facts described here.

The rule reads in one direction: every refinement key a scope carries must
appear on the addressed target with the same value, and the target may
carry keys the scope does not constrain. So a project-scoped seat covers
everything in its project, and a finer seat covers only the work matching
its refinements. When scopes nest, the most specific live covering seat
receives the message and the project seat is the fallback; no live
covering seat at all means the message parks until one arrives.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from yoke_core.domain.work_claim_scope_shape import STEERING_DOCUMENT_KEY
from yoke_core.domain.work_claim_targets import (
    TARGET_KIND_STEERING,
    decode_scope,
)


#: The outer key every steering scope carries. Refinements sit beside it.
PROJECT_KEY = "project_id"

#: The one refinement a seat carries today; re-exported for readers of the
#: rule so scope keys are named in one place.
DOCUMENT_KEY = STEERING_DOCUMENT_KEY


def scope_specificity(scope: Mapping[str, Any]) -> int:
    """How narrow one scope is; larger wins when two seats both cover."""
    return len(dict(scope))


def steering_scope_covers(
    scope: Mapping[str, Any], target: Mapping[str, Any]
) -> bool:
    """Whether a seat holding ``scope`` is the one addressed by ``target``.

    ``target`` describes the addressed work -- always its project, plus
    whatever finer facts the caller knows (its item, and later its epic,
    document, or domain). A scope constrains only the keys it names.
    """
    scope_values = dict(scope)
    target_values = dict(target)
    if PROJECT_KEY not in scope_values or PROJECT_KEY not in target_values:
        return False
    if int(scope_values[PROJECT_KEY]) != int(target_values[PROJECT_KEY]):
        return False
    for key, value in scope_values.items():
        if key == PROJECT_KEY:
            continue
        if key not in target_values or target_values[key] != value:
            return False
    return True


def scopes_overlap(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    """Whether two seats could both be addressed by one piece of work.

    Two scopes in different projects never overlap. Within one project they
    overlap unless a refinement they both name disagrees: a project seat
    and a finer seat inside it overlap, two finer seats naming different
    values of the same refinement do not.
    """
    left_values = dict(left)
    right_values = dict(right)
    if PROJECT_KEY not in left_values or PROJECT_KEY not in right_values:
        return False
    if int(left_values[PROJECT_KEY]) != int(right_values[PROJECT_KEY]):
        return False
    for key in set(left_values) & set(right_values):
        if key == PROJECT_KEY:
            continue
        if left_values[key] != right_values[key]:
            return False
    return True


def live_steering_claims(conn: Any) -> list[dict[str, Any]]:
    """Every unreleased steering claim whose holding session is still alive.

    A claim whose session has ended is not a seat. Excluding it here is what
    makes the zombie-resume class structurally impossible: no role-addressed
    message can resolve to an ended session, so nothing ever asks the relay
    to resume one in order to deliver.
    """
    from yoke_core.domain import db_backend

    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    rows = conn.execute(
        "SELECT wc.id AS claim_id, wc.session_id AS session_id, "
        "wc.scope AS scope, wc.claimed_at AS claimed_at, "
        "hs.actor_id AS actor_id "
        "FROM work_claims wc "
        "JOIN harness_sessions hs ON hs.session_id = wc.session_id "
        f"WHERE wc.target_kind = {marker} AND wc.released_at IS NULL "
        "AND hs.ended_at IS NULL AND hs.terminated_at IS NULL "
        "ORDER BY wc.claimed_at ASC, wc.id ASC",
        (TARGET_KIND_STEERING,),
    ).fetchall()
    claims: list[dict[str, Any]] = []
    for row in rows:
        record = dict(row)
        record["scope"] = decode_scope(record["scope"])
        record["claim_id"] = int(record["claim_id"])
        claims.append(record)
    return claims


def covering_claims(
    conn: Any,
    target: Mapping[str, Any],
    *,
    claims: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Live seats addressed by ``target``, most specific first."""
    candidates = list(claims) if claims is not None else live_steering_claims(conn)
    covering = [
        dict(claim)
        for claim in candidates
        if steering_scope_covers(claim["scope"], target)
    ]
    covering.sort(
        key=lambda claim: (
            -scope_specificity(claim["scope"]),
            str(claim.get("claimed_at") or ""),
            int(claim["claim_id"]),
        )
    )
    return covering


def covering_seat(
    conn: Any,
    target: Mapping[str, Any],
    *,
    claims: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """The one live seat that should receive work addressed to ``target``."""
    covering = covering_claims(conn, target, claims=claims)
    return covering[0] if covering else None


def overlapping_claims(
    conn: Any,
    scope: Mapping[str, Any],
    *,
    exclude_session_id: str | None = None,
) -> list[dict[str, Any]]:
    """Live seats whose scope could be addressed by the same work as ``scope``."""
    return [
        claim
        for claim in live_steering_claims(conn)
        if scopes_overlap(claim["scope"], scope)
        and str(claim["session_id"]) != str(exclude_session_id or "")
    ]


__all__ = [
    "DOCUMENT_KEY",
    "PROJECT_KEY",
    "covering_claims",
    "covering_seat",
    "live_steering_claims",
    "overlapping_claims",
    "scope_specificity",
    "scopes_overlap",
    "steering_scope_covers",
]
