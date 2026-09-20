"""Fill item_landings from git history that predates live close-out.

The table is append-only and keyed on ``(item_id, merge_sha)``. Close-out
writes rows as items land; everything before that writer existed is still
in git. This entry inserts those facts and leaves any row close-out already
published untouched, so a re-run and a live recording of the same merge
converge rather than collide.

``landed_at`` on a reconstructed row is the merge commit's committer time.
That is minutes early of the GitHub-observed queue merge for every
merge-queue landing, which is not recoverable from the repository. The row
says ``origin='reconstructed'`` so a reader does not treat that timestamp
as the observed moment.

Idempotent against its own output already existing: an insert that finds
the key skips. No surface is removed, so this needs no serving floor.
"""

from __future__ import annotations

from importlib import resources
from typing import Any, Iterable, Optional

from yoke_core.domain.item_landings import ItemLanding, append_landing
from yoke_core.domain.item_landings_close_out import landing_route
from yoke_core.domain.item_landings_reconstruct import (
    LandingFact,
    YOKE_PROJECT_SLUG,
    facts_from_json,
)
from yoke_core.domain.item_landings_schema import ORIGIN_RECONSTRUCTED
from yoke_core.domain.schema_common import _column_exists, _table_exists

FACTS_RESOURCE = "0046_reconstruct_item_landings.json"
PROJECTS_TABLE = "projects"
ITEMS_TABLE = "items"
LANDINGS_TABLE = "item_landings"


def _p(conn: Any) -> str:
    from yoke_core.domain import db_backend

    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _cell(row: Any, index: int, key: str) -> Any:
    """Boot converge may hand tuple rows; named test connections hand mappings."""
    return row[key] if hasattr(row, "keys") else row[index]


def load_packaged_facts() -> tuple[LandingFact, ...]:
    """The frozen git walk shipped next to this entry."""
    payload = (
        resources.files("yoke_core.domain.migrations")
        .joinpath(FACTS_RESOURCE)
        .read_text(encoding="utf-8")
    )
    return facts_from_json(payload)


def _yoke_project_id(conn: Any) -> Optional[int]:
    if not _table_exists(conn, PROJECTS_TABLE):
        return None
    p = _p(conn)
    row = conn.execute(
        f"SELECT id FROM {PROJECTS_TABLE} WHERE slug={p}",
        (YOKE_PROJECT_SLUG,),
    ).fetchone()
    if row is None:
        return None
    return int(_cell(row, 0, "id"))


def _sequence_to_item_id(conn: Any, project_id: int) -> dict[int, int]:
    if not _table_exists(conn, ITEMS_TABLE):
        return {}
    p = _p(conn)
    rows = conn.execute(
        f"SELECT id, project_sequence FROM {ITEMS_TABLE} WHERE project_id={p}",
        (project_id,),
    ).fetchall()
    mapping: dict[int, int] = {}
    for row in rows:
        sequence = _cell(row, 1, "project_sequence")
        if sequence is None:
            continue
        mapping[int(sequence)] = int(_cell(row, 0, "id"))
    return mapping


def apply_facts(conn: Any, facts: Iterable[LandingFact]) -> dict[str, int]:
    """Insert reconstructed rows. Returns written / skipped counts."""
    written = 0
    skipped_unresolved = 0
    skipped_existing = 0
    if not _table_exists(conn, LANDINGS_TABLE):
        return {
            "written": 0,
            "skipped_unresolved": 0,
            "skipped_existing": 0,
        }
    if not _column_exists(conn, LANDINGS_TABLE, "origin"):
        return {
            "written": 0,
            "skipped_unresolved": 0,
            "skipped_existing": 0,
        }
    project_id = _yoke_project_id(conn)
    if project_id is None:
        return {
            "written": 0,
            "skipped_unresolved": 0,
            "skipped_existing": 0,
        }
    items = _sequence_to_item_id(conn, project_id)
    for fact in facts:
        item_id = items.get(int(fact.project_sequence))
        if item_id is None:
            skipped_unresolved += 1
            continue
        appended = append_landing(
            conn,
            ItemLanding(
                item_id=item_id,
                merge_sha=fact.merge_sha,
                candidate_sha=fact.candidate_sha,
                pr_number=fact.pr_number,
                target_branch=fact.target_branch,
                route=landing_route(
                    merge_sha=fact.merge_sha,
                    candidate_sha=fact.candidate_sha,
                    pr_number=fact.pr_number,
                ),
                landed_at=fact.landed_at,
                origin=ORIGIN_RECONSTRUCTED,
            ),
        )
        if appended:
            written += 1
        else:
            skipped_existing += 1
    return {
        "written": written,
        "skipped_unresolved": skipped_unresolved,
        "skipped_existing": skipped_existing,
    }


def apply(conn: Any) -> None:
    """Insert every packaged fact that resolves to a live yoke item."""
    apply_facts(conn, load_packaged_facts())


__all__ = [
    "FACTS_RESOURCE",
    "apply",
    "apply_facts",
    "load_packaged_facts",
]
