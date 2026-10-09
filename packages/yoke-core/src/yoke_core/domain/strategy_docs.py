"""DB-authoritative strategy documents and CAS writes; files are rendered views."""

from __future__ import annotations

from datetime import datetime
from yoke_contracts.timestamps import utc_now, parse_instant, format_instant
from yoke_core.domain.db_helpers import instant_parameter
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from yoke_contracts.project_contract.strategy_docs_io import (
    StrategyDocSlugError,
    require_strategy_doc_slug,
)
from yoke_contracts.project_contract.strategy_doc_fields import normalize_fields
from yoke_core.domain import strategy_docs_header as _header
from yoke_core.domain.strategy_doc_presentation import summary_from_row
from yoke_core.domain.strategy_docs_defaults import DEFAULT_STRATEGY_DOC_SLUGS
from yoke_core.domain.strategy_docs_schema import (
    STRATEGY_DOCS_TABLE,
    record_doc_revision,
)

StrategyHeaderError = _header.StrategyHeaderError

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


def next_updated_at() -> datetime:
    """Mint a native microsecond clock for the strategy document CAS token."""
    return utc_now()


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
    """Return one display summary row per strategy document.

    ``archived`` is ``True`` when the doc carries an ``archived_at`` stamp.
    ``updated_by`` is the last editor's resolved display label (or ``None``):
    the stored identity is the numeric actor id, resolved to a label here for
    display only, the same projection the render header uses.
    """
    rows = conn.execute(
        f"SELECT slug, updated_at, updated_by_actor_id, content, archived_at "
        f"FROM {STRATEGY_DOCS_TABLE} WHERE project_id = %s",
        (project_id,),
    ).fetchall()
    order = {slug: i for i, slug in enumerate(DEFAULT_STRATEGY_DOC_SLUGS)}
    docs = [summary_from_row(conn, row) for row in rows]
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
    """Return ``{slug, content, updated_at, updated_by_actor_id, archived_at}``.

    Editor ids remain native; declared clock fields are fixed-six UTC/null.
    Invalid slugs and absent rows raise the named strategy-document errors.
    """
    _require_valid_slug(slug)
    row = conn.execute(
        f"SELECT slug, content, updated_at, updated_by_actor_id, archived_at "
        f"FROM {STRATEGY_DOCS_TABLE} "
        "WHERE project_id = %s AND slug = %s",
        (project_id, slug),
    ).fetchone()
    if row is None:
        raise StrategyDocMissingError(missing_doc_teaching(conn, project_id, slug))
    actor = row["updated_by_actor_id"]
    archived_at = row["archived_at"]
    return {
        "slug": str(row["slug"]),
        "content": str(row["content"]),
        "updated_at": format_instant(row["updated_at"]),
        "updated_by_actor_id": int(actor) if actor is not None else None,
        "archived_at": format_instant(archived_at) if archived_at is not None else None,
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
    base_updated_at: str | datetime,
    force: bool = False,
    session_id: Optional[str] = None,
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
    base = parse_instant(base_updated_at)
    content = _header.strip_render_header_if_present(str(content), expected_slug=slug)
    if not content or not content.strip():
        raise EmptyStrategyDocError(
            f"refusing to replace strategy doc {slug!r} with empty content; "
            "strategy docs are never blanked through this surface."
        )
    content = normalize_fields(content)
    old = get_doc(conn, project_id, slug)
    old_bytes = _byte_len(old["content"])
    new_bytes = _byte_len(content)
    if content == old["content"] and base == parse_instant(old["updated_at"]):
        # Only a fresh identical write is a no-op; stale bases still hit CAS.
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
        (
            content,
            instant_parameter(conn, updated_at),
            actor_id,
            project_id,
            slug,
            instant_parameter(conn, base),
        ),
    )
    if cur.rowcount == 0:
        raise StrategyDocConflictError(replace_conflict_teaching(slug))
    record_doc_revision(
        conn,
        project_id,
        slug,
        content,
        source_operation="replace",
        actor_id=actor_id,
        created_at=updated_at,
        session_id=session_id,
    )
    conn.commit()
    return {
        "slug": slug,
        "old_bytes": old_bytes,
        "new_bytes": new_bytes,
        "updated_at": format_instant(updated_at),
    }


def set_doc_archived(
    conn: Any,
    project_id: int,
    slug: str,
    *,
    archived: bool,
) -> Dict[str, Any]:
    """Flip one doc's archived state; return the change report.

    Archiving stamps ``archived_at`` with the current timestamp;
    unarchiving clears it back to NULL. The doc's ``content`` and
    ``updated_at`` are untouched — archiving is orthogonal to content
    editing, so an archived doc renders byte-identically (just relocated
    to ``.yoke/strategy/archive/``) and stays a full, editable corpus row.

    Idempotent: flipping to the state a doc is already in is a no-op that
    returns ``changed=False`` rather than raising. Raises
    :class:`UnknownStrategyDocError` for an invalid slug and
    :class:`StrategyDocMissingError` when the project has no row for the
    slug. Returns ``{slug, archived, archived_at, changed}``.
    """
    _require_valid_slug(slug)
    doc = get_doc(conn, project_id, slug)
    currently_archived = doc["archived_at"] is not None
    if currently_archived == archived:
        return {
            "slug": slug,
            "archived": archived,
            "archived_at": doc["archived_at"],
            "changed": False,
        }
    new_archived_at = next_updated_at() if archived else None
    conn.execute(
        f"UPDATE {STRATEGY_DOCS_TABLE} SET archived_at = %s "
        "WHERE project_id = %s AND slug = %s",
        (instant_parameter(conn, new_archived_at), project_id, slug),
    )
    conn.commit()
    return {
        "slug": slug,
        "archived": archived,
        "archived_at": format_instant(new_archived_at)
        if new_archived_at is not None
        else None,
        "changed": True,
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

    ``slugs`` selects a subset; ``None`` renders the full corpus.
    An empty corpus raises ``StrategyDocMissingError`` with seed guidance.
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
    "set_doc_archived",
]
