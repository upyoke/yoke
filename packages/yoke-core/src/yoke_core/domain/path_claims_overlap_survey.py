"""Consult recorded conflict surveys while classifying a path claim.

Path-claim classification compares ``path_claim_targets`` membership, so
it sees only work that has already registered a claim. A direct-workflow
item that recorded a survey has declared exactly the same thing — these
are my edit targets on this integration target — without a claim row to
compare against, and an ordinary Issue could therefore register a claim
straight through a live declaration and be told the surface was free.

This module closes that direction. It applies the same directional rules
the claim-pair classifier applies, at item granularity because a survey
has no claim id: a coordination-only pair proceeds, a candidate that is
the DEPENDENT of a serial edge serializes, a candidate that is the
BLOCKER of one is upstream and does not wait, and an unattested overlap
is incompatible.
"""

from __future__ import annotations

from typing import Any, Optional, Sequence, Tuple

from yoke_core.domain import db_backend
from yoke_core.domain.conflict_survey_declared_paths import (
    DeclaredSurvey,
    declared_surveys,
    matching_scope,
)
from yoke_core.domain.path_claims_overlap import OverlapClassification


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _candidate_paths(conn: Any, target_ids: Sequence[int]) -> Tuple[str, ...]:
    if not target_ids:
        return ()
    placeholders = ",".join(_p(conn) for _ in target_ids)
    rows = conn.execute(
        f"SELECT path_string FROM path_targets WHERE id IN ({placeholders})",
        tuple(target_ids),
    ).fetchall()
    return tuple(str(row[0]) for row in rows)


def _candidate_project_id(conn: Any, target_ids: Sequence[int]) -> Optional[int]:
    if not target_ids:
        return None
    row = conn.execute(
        f"SELECT project_id FROM path_targets WHERE id = {_p(conn)}",
        (int(target_ids[0]),),
    ).fetchone()
    return None if row is None or row[0] is None else int(row[0])


def survey_overlaps(
    conn: Any,
    *,
    target_ids: Sequence[int],
    integration_target: str,
    candidate_item_id: Optional[int],
) -> list[tuple[DeclaredSurvey, str]]:
    """Return each live survey the candidate coverage lands on, with the path."""
    project_id = _candidate_project_id(conn, target_ids)
    if project_id is None:
        return []
    paths = _candidate_paths(conn, target_ids)
    if not paths:
        return []
    matches: list[tuple[DeclaredSurvey, str]] = []
    for survey in declared_surveys(
        conn,
        project_id=project_id,
        integration_target=integration_target,
        exclude_item_id=candidate_item_id,
    ):
        matched = matching_scope(survey.paths, paths)
        if matched:
            matches.append((survey, matched))
    return matches


def classify_survey_overlap(
    conn: Any,
    *,
    target_ids: Sequence[int],
    integration_target: str,
    candidate_item_id: Optional[int],
) -> OverlapClassification:
    """Classify the candidate coverage against live declared surveys."""
    from yoke_core.domain.path_claims_dependency_resolver_coordination import (
        has_forward_serial_edge,
        items_are_coordination_only,
    )

    matched_upstream = False
    for survey, _path in survey_overlaps(
        conn,
        target_ids=target_ids,
        integration_target=integration_target,
        candidate_item_id=candidate_item_id,
    ):
        if candidate_item_id is None:
            return OverlapClassification.INCOMPATIBLE
        if items_are_coordination_only(
            conn, item_a_id=int(candidate_item_id), item_b_id=survey.item_id,
        ):
            continue
        if has_forward_serial_edge(
            conn,
            dependent_item_id=int(candidate_item_id),
            blocking_item_id=survey.item_id,
        ):
            matched_upstream = True
            continue
        if has_forward_serial_edge(
            conn,
            dependent_item_id=survey.item_id,
            blocking_item_id=int(candidate_item_id),
        ):
            continue
        return OverlapClassification.INCOMPATIBLE
    return (
        OverlapClassification.SERIAL_VIA_DEPENDENCY
        if matched_upstream
        else OverlapClassification.NONE
    )


def describe_survey_overlap(
    conn: Any,
    *,
    target_ids: Sequence[int],
    integration_target: str,
    candidate_item_id: Optional[int],
) -> str:
    """Name the surveying item and path so a refusal says which door is held."""
    from yoke_core.domain.project_identity import render_item_ref

    matches = survey_overlaps(
        conn,
        target_ids=target_ids,
        integration_target=integration_target,
        candidate_item_id=candidate_item_id,
    )
    if not matches:
        return ""
    survey, path = matches[0]
    return (
        f"path coverage overlaps the recorded Conflict Survey of "
        f"{render_item_ref(conn, survey.item_id)} on {path!r} "
        f"({survey.status}, declared intent rather than a registered claim); "
        "coordinate with that item, declare an upstream dependency, or wait"
    )


__all__ = [
    "classify_survey_overlap",
    "describe_survey_overlap",
    "survey_overlaps",
]
