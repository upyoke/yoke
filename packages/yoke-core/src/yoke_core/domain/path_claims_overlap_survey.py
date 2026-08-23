"""Report recorded conflict surveys as path-claim advisories.

Path-claim classification compares ``path_claim_targets`` membership, so
it intentionally sees only work that has reserved coverage. A recorded
survey is weaker: it declares intent before a claim exists, so overlap is
reported for agent judgement but never feeds the claim verdict.
"""

from __future__ import annotations

from typing import Any, Optional, Sequence, Tuple

from yoke_core.domain import db_backend
from yoke_core.domain.conflict_survey_declared_paths import (
    DeclaredSurvey,
    declared_surveys,
    matching_scope,
)
from yoke_core.domain.schema_common import _column_exists, _table_exists
from yoke_core.domain.path_render_overlap import is_render_target_only_overlap

SURVEY_ADVISORY_PROCEED = (
    "Proceed when the edits are independent; same-file collisions resolve at merge."
)
SURVEY_ADVISORY_YIELD = (
    "Yield by authoring an activation dependency from this item to the other "
    "item, dropping this claim, and re-offering the item to the engine."
)

# ``classify_overlap`` is exercised against deliberately minimal schemas
# that carry path claims without the item columns a survey is scoped by.
# On Postgres a query against a missing column aborts the surrounding
# transaction, so the shape is checked before the read, never caught
# after it.
_REQUIRED_ITEM_COLUMNS = ("project_id", "status")
_REQUIRED_TABLES = ("items", "item_sections", "path_targets")


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


def _schema_supports_survey_coordination(conn: Any) -> bool:
    """Whether this database exposes the surfaces a survey read needs."""
    if not all(_table_exists(conn, table) for table in _REQUIRED_TABLES):
        return False
    if not _column_exists(conn, "path_targets", "path_string"):
        return False
    return all(
        _column_exists(conn, "items", column) for column in _REQUIRED_ITEM_COLUMNS
    )


def _item_project_id(conn: Any, item_id: int) -> Optional[int]:
    """Resolve the candidate's project from the item that owns the claim.

    The item row is the typed authority. Reading the project off a path
    target instead would inherit whatever that column happens to hold,
    and a project we cannot resolve leaves the claim-side door lock as
    the only check rather than crashing the caller.
    """
    row = conn.execute(
        f"SELECT project_id FROM items WHERE id = {_p(conn)}",
        (int(item_id),),
    ).fetchone()
    if row is None or row[0] is None:
        return None
    try:
        return int(row[0])
    except (TypeError, ValueError):
        return None


def survey_overlaps(
    conn: Any,
    *,
    target_ids: Sequence[int],
    integration_target: str,
    candidate_item_id: Optional[int],
) -> list[tuple[DeclaredSurvey, str]]:
    """Return each live survey the candidate coverage lands on, with the path.

    Survey coordination is item-to-item: a claim with no owning item
    carries no identity to coordinate against and no declared edges to
    classify direction from, so it consults nothing here and the
    claim-side classification stands alone.
    """
    if candidate_item_id is None:
        return []
    if not _schema_supports_survey_coordination(conn):
        return []
    project_id = _item_project_id(conn, candidate_item_id)
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
        if matched and not is_render_target_only_overlap(
            conn,
            candidate_paths=paths,
            other_paths=survey.paths,
            project_id=project_id,
        ):
            matches.append((survey, matched))
    return matches


def describe_survey_overlap(
    conn: Any,
    *,
    target_ids: Sequence[int],
    integration_target: str,
    candidate_item_id: Optional[int],
) -> str:
    """Render live survey overlap and the two available agent routes."""
    from yoke_core.domain.project_identity import render_item_ref

    matches = survey_overlaps(
        conn,
        target_ids=target_ids,
        integration_target=integration_target,
        candidate_item_id=candidate_item_id,
    )
    if not matches:
        return ""
    overlaps = "; ".join(
        f"{render_item_ref(conn, survey.item_id)} ({survey.status}) on {path!r}"
        for survey, path in matches
    )
    return (
        f"survey advisory: declared paths overlap {overlaps}. "
        f"{SURVEY_ADVISORY_PROCEED} {SURVEY_ADVISORY_YIELD}"
    )


def describe_claim_survey_overlap(
    conn: Any,
    *,
    claim_id: int,
    integration_target: str,
    candidate_item_id: Optional[int],
) -> str:
    """Render survey overlap for one claim's declared target ids."""
    if not _table_exists(conn, "path_claim_targets"):
        return ""
    rows = conn.execute(
        f"SELECT target_id FROM path_claim_targets WHERE claim_id = {_p(conn)}",
        (int(claim_id),),
    ).fetchall()
    return describe_survey_overlap(
        conn,
        target_ids=[int(row[0]) for row in rows],
        integration_target=integration_target,
        candidate_item_id=candidate_item_id,
    )


__all__ = [
    "SURVEY_ADVISORY_PROCEED",
    "SURVEY_ADVISORY_YIELD",
    "describe_claim_survey_overlap",
    "describe_survey_overlap",
    "survey_overlaps",
]
