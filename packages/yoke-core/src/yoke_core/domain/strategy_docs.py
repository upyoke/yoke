"""Strategy-doc authority: per-project DB-owned docs + rendered repo views.

The Yoke DB ``strategy_docs`` table is the single authority for every
project's strategy documents, keyed ``(project_id, slug)`` — a project's
corpus is exactly its rows, with no global slug canon (cold starts mint
the :data:`yoke_core.domain.strategy_docs_defaults.DEFAULT_STRATEGY_DOC_SLUGS`
placeholders). Each project's ``.yoke/strategy/`` directory holds
**tracked rendered views** — the ``docs/atlas.md`` precedent, NOT the
untracked ``.yoke/BOARD.md`` one: the files stay in git (git is the
revision store), :func:`render_docs` is the only writer of those files,
and reads always come from the DB. The directory location resolves
through :mod:`yoke_core.domain.strategy_docs_paths` (the future
per-project override seam).

Each rendered file begins with the idempotent strategy-doc header (slug,
row ``updated_at``, content sha256, and DB-is-authoritative notice).
Operator edits to rendered files write back through the compare-and-swap
``strategy.ingest.run`` path.

The renderer takes an explicit ``target_root`` kwarg and never resolves
an ambient cwd.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from yoke_contracts.project_contract.strategy_docs_io import (
    StrategyDocSlugError,
    require_strategy_doc_slug,
)
from yoke_core.domain import strategy_docs_header as _header
from yoke_core.domain.strategy_docs_defaults import DEFAULT_STRATEGY_DOC_SLUGS

StrategyHeaderError = _header.StrategyHeaderError
STRATEGY_DOCS_TABLE = "strategy_docs"

# No FK to actors: validation DBs may carry no actors rows; provenance
# only, never joined for authority. The projects FK is real authority —
# every corpus belongs to exactly one project.
STRATEGY_DOCS_CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {STRATEGY_DOCS_TABLE} (
  id BIGSERIAL PRIMARY KEY,
  project_id BIGINT NOT NULL REFERENCES projects(id),
  slug TEXT NOT NULL,
  content TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL,
  updated_by_actor_id BIGINT
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_strategy_docs_project_id_slug
  ON {STRATEGY_DOCS_TABLE}(project_id, slug)
"""

# replace_doc refuses a write shrinking content below this fraction of
# the old byte length unless force=True.
SHRINK_GUARD_RATIO = 0.6

class UnknownStrategyDocError(ValueError):
    """Raised for a slug whose shape can never name a strategy doc."""


class EmptyStrategyDocError(ValueError):
    """Raised when a replace would land empty/whitespace-only content."""


class StrategyDocShrinkError(ValueError):
    """Raised when a replace shrinks content below the guard ratio without force."""


class StrategyDocMissingError(LookupError):
    """Raised when a project has no row for the requested slug."""


class StrategyDocConflictError(RuntimeError):
    """Raised when a CAS write's base ``updated_at`` no longer matches."""


def next_updated_at() -> str:
    """Microsecond-precision UTC stamp for strategy-doc writes.

    ``updated_at`` is the compare-and-swap token for replace and ingest;
    at the canonical second resolution two writes landing inside the
    same second would re-mint an identical token and the CAS could not
    tell the second writer's base was stale. Fractional seconds keep the token unique per
    write while staying ISO-8601 sortable next to second-precision
    rows seeded by the migration.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _byte_len(content: str) -> int:
    return len(content.encode("utf-8"))


def _require_valid_slug(slug: str) -> str:
    try:
        return require_strategy_doc_slug(slug)
    except StrategyDocSlugError as exc:
        raise UnknownStrategyDocError(str(exc)) from exc


def project_doc_slugs(conn: Any, project_id: int) -> List[str]:
    """Return the project's corpus — its row slugs in display order.

    Display order: the default starter slugs first (mission before
    plan), then any further docs alphabetically. The corpus itself is
    defined by the rows; this ordering is presentation only.
    """
    rows = conn.execute(
        f"SELECT slug FROM {STRATEGY_DOCS_TABLE} WHERE project_id = %s",
        (project_id,),
    ).fetchall()
    order = {slug: i for i, slug in enumerate(DEFAULT_STRATEGY_DOC_SLUGS)}
    slugs = [str(r["slug"] if hasattr(r, "keys") else r[0]) for r in rows]
    slugs.sort(key=lambda s: (order.get(s, len(order)), s))
    return slugs


def list_docs(conn: Any, project_id: int) -> List[Dict[str, Any]]:
    """Return one ``{slug, updated_at, updated_by, bytes}`` row per doc.

    ``updated_by`` is the last editor's resolved display label (or ``None``):
    the stored identity is the numeric actor id, resolved to a label here for
    display only, the same projection the render header uses.
    """
    from yoke_core.domain.actor_render import actor_render_label

    rows = conn.execute(
        f"SELECT slug, updated_at, updated_by_actor_id, content "
        f"FROM {STRATEGY_DOCS_TABLE} WHERE project_id = %s",
        (project_id,),
    ).fetchall()
    order = {slug: i for i, slug in enumerate(DEFAULT_STRATEGY_DOC_SLUGS)}
    docs = [
        {
            "slug": str(row["slug"]),
            "updated_at": str(row["updated_at"]),
            "updated_by": actor_render_label(conn, row["updated_by_actor_id"]),
            "bytes": _byte_len(str(row["content"])),
        }
        for row in rows
    ]
    docs.sort(key=lambda d: (order.get(d["slug"], len(order)), d["slug"]))
    return docs


def missing_doc_teaching(conn: Any, project_id: int, slug: str) -> str:
    """Name the project's actual corpus when a slug has no row."""
    corpus = project_doc_slugs(conn, project_id)
    if corpus:
        return (
            f"project {project_id} has no strategy doc {slug!r}; its corpus "
            f"is: {', '.join(corpus)}. A project's doc set is exactly its "
            "rows — there is no doc-creation surface on this path."
        )
    return (
        f"project {project_id} has no strategy docs at all. Cold-start the "
        "default corpus first: yoke strategy seed-defaults --project "
        f"{project_id}"
    )


def get_doc(conn: Any, project_id: int, slug: str) -> Dict[str, Any]:
    """Return ``{slug, content, updated_at, updated_by_actor_id}`` for a doc.

    ``updated_by_actor_id`` is the int id of the last editor (or ``None``);
    the render path resolves it to a display label. Raises
    :class:`UnknownStrategyDocError` for an invalid slug shape and
    :class:`StrategyDocMissingError` (teaching the project's actual corpus)
    when the project has no row for the slug.
    """
    _require_valid_slug(slug)
    row = conn.execute(
        f"SELECT slug, content, updated_at, updated_by_actor_id "
        f"FROM {STRATEGY_DOCS_TABLE} "
        "WHERE project_id = %s AND slug = %s",
        (project_id, slug),
    ).fetchone()
    if row is None:
        raise StrategyDocMissingError(missing_doc_teaching(conn, project_id, slug))
    actor = row["updated_by_actor_id"]
    return {
        "slug": str(row["slug"]),
        "content": str(row["content"]),
        "updated_at": str(row["updated_at"]),
        "updated_by_actor_id": int(actor) if actor is not None else None,
    }


def replace_conflict_teaching(slug: str) -> str:
    """Canonical recovery teaching for a CAS conflict on ``replace``."""
    return (
        f"strategy doc {slug!r} changed in the DB after the content you "
        "based this write on was read — refusing the write so the newer "
        "content is not lost. Re-read the current doc (`yoke strategy "
        f"doc get {slug}`), re-apply your changes onto it, and replace "
        "again with the fresh updated_at as --base-updated-at."
    )


def replace_doc(
    conn: Any,
    project_id: int,
    slug: str,
    content: str,
    actor_id: Optional[int],
    *,
    base_updated_at: str,
    force: bool = False,
) -> Dict[str, Any]:
    """CAS-replace one of the project's docs; return the byte report.

    Every replace is a compare-and-swap on ``base_updated_at`` — the
    row's ``updated_at`` the caller read before authoring; there is
    no blind-write path. Guards (raise instead of writing):

    - invalid slug shape → :class:`UnknownStrategyDocError`;
    - no row for ``(project_id, slug)`` → :class:`StrategyDocMissingError`
      (no doc creation through replace);
    - empty/whitespace-only content → :class:`EmptyStrategyDocError`;
    - new content under ``SHRINK_GUARD_RATIO`` of the old byte length
      without ``force=True`` → :class:`StrategyDocShrinkError`;
    - row moved past ``base_updated_at`` → :class:`StrategyDocConflictError`
      (``force`` does NOT bypass — re-read first, always).

    Commits on success and returns ``{slug, old_bytes, new_bytes,
    updated_at}``.
    """
    _require_valid_slug(slug)
    if not base_updated_at or not str(base_updated_at).strip():
        raise ValueError(
            "base_updated_at is required: pass the updated_at you read "
            f"from `yoke strategy doc get {slug}` so the write is "
            "compare-and-swap protected."
        )
    content = _header.strip_render_header_if_present(str(content), expected_slug=slug)
    if not content or not content.strip():
        raise EmptyStrategyDocError(
            f"refusing to replace strategy doc {slug!r} with empty content; "
            "strategy docs are never blanked through this surface."
        )
    old = get_doc(conn, project_id, slug)
    old_bytes = _byte_len(old["content"])
    new_bytes = _byte_len(content)
    if content == old["content"] and str(base_updated_at) == old["updated_at"]:
        # No-op write: identical content from a caller whose base is still
        # the live row. Skip the UPDATE so updated_at / updated_by_actor_id
        # are NOT advanced — a write that changes nothing must not move the
        # row, or the tracked .yoke/strategy/ view churns (a fresh CAS
        # timestamp lands in the render header) with no real edit.
        #
        # The base-freshness half of the guard is load-bearing: a STALE base
        # whose content only coincidentally equals the current row is still a
        # lost-update hazard (the caller authored against an older version
        # they never re-read) and MUST conflict, not silently no-op. Dropping
        # that check lets the stale write return success here and skip the CAS
        # entirely. When
        # the base is stale we fall through to the UPDATE below, whose
        # ``WHERE updated_at = base`` clause matches zero rows and raises.
        return {
            "slug": slug,
            "old_bytes": old_bytes,
            "new_bytes": new_bytes,
            "updated_at": old["updated_at"],
            "unchanged": True,
        }
    if not force and new_bytes < old_bytes * SHRINK_GUARD_RATIO:
        raise StrategyDocShrinkError(
            f"refusing to shrink strategy doc {slug!r} from {old_bytes} to "
            f"{new_bytes} bytes (<{int(SHRINK_GUARD_RATIO * 100)}% of old "
            "length). Pass force=True only for an intentional rewrite."
        )
    updated_at = next_updated_at()
    cur = conn.execute(
        f"UPDATE {STRATEGY_DOCS_TABLE} "
        "SET content = %s, updated_at = %s, updated_by_actor_id = %s "
        "WHERE project_id = %s AND slug = %s AND updated_at = %s",
        (content, updated_at, actor_id, project_id, slug, str(base_updated_at)),
    )
    if cur.rowcount == 0:
        raise StrategyDocConflictError(replace_conflict_teaching(slug))
    conn.commit()
    return {
        "slug": slug,
        "old_bytes": old_bytes,
        "new_bytes": new_bytes,
        "updated_at": updated_at,
    }


def render_docs(
    *,
    target_root: Path,
    project_id: int,
    slugs: Optional[Sequence[str]] = None,
) -> Dict[str, str]:
    """Render the project's docs (header + content) to ``.yoke/strategy/``.

    In-process composition of the two-half transport split: fetch the
    row→file-text map and write it locally in one call (tests, fixtures,
    and checkout-local code paths). Remote callers compose the same two
    halves across the wire — ``strategy.render.run`` returns the map and
    the CLI writes it. Returns the per-slug ``"written"``/``"unchanged"``
    report.

    ``slugs`` narrows the render to a subset (the ingest write-back path
    re-renders exactly the docs it wrote); ``None`` renders the
    project's full corpus or fails — rendering a partial set would
    silently drop docs from the view. A project with zero rows raises
    :class:`StrategyDocMissingError` teaching the seed-defaults cold
    start.
    """
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.strategy_docs_render import (
        render_file_map,
        write_rendered_files,
    )

    with connect() as conn:
        files = render_file_map(conn, project_id, slugs)
    return write_rendered_files(Path(target_root), files)


__all__ = [
    "EmptyStrategyDocError",
    "SHRINK_GUARD_RATIO",
    "STRATEGY_DOCS_CREATE_TABLE_SQL",
    "STRATEGY_DOCS_TABLE",
    "StrategyDocConflictError",
    "StrategyDocMissingError",
    "StrategyDocShrinkError",
    "UnknownStrategyDocError",
    "get_doc",
    "list_docs",
    "missing_doc_teaching",
    "next_updated_at",
    "project_doc_slugs",
    "render_docs",
    "replace_conflict_teaching",
    "replace_doc",
]
