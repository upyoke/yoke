"""One central rule for which steering scope covers which work.

A steering seat is addressed as a role rather than as a session id, so
something has to decide which live seat a role-addressed message belongs
to. That decision is this rule and nothing else. It is deliberately not a
stored column: the answer changes the moment a seat is taken or released,
and a precomputed copy would be stale exactly during the handoff the role
addressing exists to survive.

A steering claim is scoped ``{"project_id": N}`` for a whole project, or
``{"project_id": N, "document": "SLUG"}`` for one strategy document. ``N``
on a document seat is the document's owning project, not the item's
execution project. The scope object is validated by
:mod:`yoke_core.domain.work_claim_scope_shape`.

Which items a document scope covers is not this module's decision: the
addressed work arrives already described, and
:mod:`yoke_core.domain.steering_scope_membership` is what turns an item
into the facts described here.

Project steering covers items owned by that project that are unlinked
or linked to that project's CURRENT-PLAN. An item linked to any other
document is excluded, even when no document seat is live, so it stays
unattended rather than falling back. Document steering covers every item
linked to that exact document, including items owned by other projects.
When two live seats both cover, the most specific wins; none means park.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from yoke_core.domain.schema_common import _column_exists, _table_exists
from yoke_core.domain.strategy_docs_defaults import NEAR_TERM_PLAN_SLUG
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

#: Owning project of the linked document, distinct from the item's project.
DOCUMENT_PROJECT_KEY = "document_project_id"


def scope_specificity(scope: Mapping[str, Any]) -> int:
    """How narrow one scope is; larger wins when two seats both cover."""
    return len(dict(scope))


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def target_document_identity(
    target: Mapping[str, Any],
) -> tuple[int, str] | None:
    """Owning project plus slug of the document the addressed work belongs to."""
    slug = dict(target).get(DOCUMENT_KEY)
    if not slug:
        return None
    project = dict(target).get(DOCUMENT_PROJECT_KEY, target.get(PROJECT_KEY))
    project_id = _int_or_none(project)
    if project_id is None:
        return None
    return project_id, str(slug)


def _scope_document_identity(
    scope: Mapping[str, Any],
) -> tuple[int, str] | None:
    slug = dict(scope).get(DOCUMENT_KEY)
    project_id = _int_or_none(dict(scope).get(PROJECT_KEY))
    if not slug or project_id is None:
        return None
    return project_id, str(slug)


def _other_refinements_match(
    scope_values: Mapping[str, Any], target_values: Mapping[str, Any]
) -> bool:
    for key, value in scope_values.items():
        if key in (PROJECT_KEY, DOCUMENT_KEY):
            continue
        if key not in target_values or target_values[key] != value:
            return False
    return True


def steering_scope_covers(
    scope: Mapping[str, Any], target: Mapping[str, Any]
) -> bool:
    """Whether a seat holding ``scope`` is the one addressed by ``target``.

    ``target`` always names the item's execution ``project_id``. When the
    item is linked, it also names ``document`` and
    ``document_project_id`` so a document seat can match across projects.
    """
    scope_values = dict(scope)
    target_values = dict(target)
    if PROJECT_KEY not in scope_values or PROJECT_KEY not in target_values:
        return False
    scope_document = _scope_document_identity(scope_values)
    if scope_document is not None:
        return (
            target_document_identity(target_values) == scope_document
            and _other_refinements_match(scope_values, target_values)
        )
    if int(scope_values[PROJECT_KEY]) != int(target_values[PROJECT_KEY]):
        return False
    linked = target_document_identity(target_values)
    if linked is not None and linked != (
        int(scope_values[PROJECT_KEY]),
        NEAR_TERM_PLAN_SLUG,
    ):
        return False
    return _other_refinements_match(scope_values, target_values)


def scopes_overlap(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    """Whether two seats could both be addressed by one piece of work.

    A project seat overlaps CURRENT-PLAN document steering of the same
    project. It does not overlap any other document, so those seats can run
    concurrently. Two documents overlap only when they are the same
    owning-project-plus-slug identity. Shared non-document refinements that
    disagree still keep two seats apart.
    """
    left_values = dict(left)
    right_values = dict(right)
    left_doc = _scope_document_identity(left_values)
    right_doc = _scope_document_identity(right_values)
    if left_doc is None and right_doc is None:
        if PROJECT_KEY not in left_values or PROJECT_KEY not in right_values:
            return False
        if int(left_values[PROJECT_KEY]) != int(right_values[PROJECT_KEY]):
            return False
    elif left_doc is not None and right_doc is not None:
        if left_doc != right_doc:
            return False
    else:
        project = left_values if left_doc is None else right_values
        document = left_doc or right_doc
        if PROJECT_KEY not in project:
            return False
        if document != (int(project[PROJECT_KEY]), NEAR_TERM_PLAN_SLUG):
            return False
    for key in set(left_values) & set(right_values):
        if key in (PROJECT_KEY, DOCUMENT_KEY):
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

    if not _table_exists(conn, "work_claims") or not _table_exists(
        conn, "harness_sessions"
    ):
        return []
    actor = (
        "hs.actor_id AS actor_id"
        if _column_exists(conn, "harness_sessions", "actor_id")
        else "NULL AS actor_id"
    )
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    rows = conn.execute(
        "SELECT wc.id AS claim_id, wc.session_id AS session_id, "
        f"wc.scope AS scope, wc.claimed_at AS claimed_at, {actor} "
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
    "DOCUMENT_PROJECT_KEY",
    "PROJECT_KEY",
    "covering_claims",
    "covering_seat",
    "live_steering_claims",
    "overlapping_claims",
    "scope_specificity",
    "scopes_overlap",
    "steering_scope_covers",
    "target_document_identity",
]
