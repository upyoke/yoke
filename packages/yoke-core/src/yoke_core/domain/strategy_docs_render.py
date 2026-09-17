"""Row→file-text map + local file writes for strategy-doc renders.

The 12942 transport split: ``strategy.render.run`` returns rendered
file texts (header + content) and the CALLER writes them into its own
checkout, so the server never touches a filesystem path that only
exists on the operator machine. :func:`render_file_map` is the
server/in-process half (rows → texts); :func:`write_rendered_files` is
the client half (texts → ``.yoke/strategy/`` files, byte-idempotent),
shared by the ``yoke strategy render`` adapter, the ingest write-back
header advance, and the in-process composition
:func:`yoke_core.domain.strategy_docs.render_docs`.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from yoke_contracts.project_contract.strategy_docs_header import (
    content_sha256,
    render_file_text,
)
from yoke_contracts.project_contract.strategy_docs_io import write_rendered_files


def _known_by_slug(known: Optional[Iterable[Mapping[str, Any]]]) -> Dict[str, Mapping[str, Any]]:
    return {
        str(entry["slug"]): entry
        for entry in (known or ())
        if entry.get("slug")
    }


def _row_matches_known(row: Mapping[str, Any], known: Mapping[str, Any]) -> bool:
    archived = row.get("archived_at") is not None
    return (
        str(known.get("updated_at") or "") == str(row["updated_at"])
        and str(known.get("content_sha256") or "") == content_sha256(str(row["content"]))
        and bool(known.get("archived", False)) is archived
    )


def render_file_map(
    conn: Any,
    project_id: int,
    slugs: Optional[Sequence[str]] = None,
    *,
    include_archives: bool = True,
    known: Optional[Iterable[Mapping[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Return per-doc render entries for the selected corpus.

    Each entry carries ``slug``, ``updated_at``, ``archived``,
    ``content_sha256``, ``bytes``, and ``unchanged``. ``file_text`` (the
    complete rendered file) is present only when the client must write
    bytes: a first fetch, a changed row, or an archive-location flip.
    ``slugs`` narrows to a subset and includes archived docs named
    explicitly. ``None`` maps the project's rows, including archives
    when ``include_archives`` is true (the in-process / install default)
    and skipping them otherwise. A project with zero selected rows
    raises :class:`yoke_core.domain.strategy_docs.StrategyDocMissingError`
    teaching the seed-defaults cold start. Surfaces
    :class:`yoke_core.domain.strategy_docs_header.StrategyHeaderError`
    (``kind="content_has_header"``) from :func:`render_file_text` when a
    row's ``content`` is itself a rendered file — the render boundary
    refuses to stack a second header rather than emit a corrupt view.
    """
    from yoke_core.domain.actor_render import render_actor_name
    from yoke_core.domain.strategy_docs import (
        StrategyDocMissingError,
        _require_valid_slug,
        get_doc,
        missing_doc_teaching,
        project_doc_slugs,
    )
    from yoke_core.domain.strategy_docs_schema import STRATEGY_DOCS_TABLE

    known_map = _known_by_slug(known)
    if slugs:
        wanted = tuple(_require_valid_slug(slug) for slug in slugs)
        rows_by_slug = {
            slug: get_doc(conn, project_id, slug) for slug in wanted
        }
        ordered = wanted
    else:
        ordered = tuple(project_doc_slugs(conn, project_id))
        if not include_archives:
            rows = conn.execute(
                f"SELECT slug, content, updated_at, updated_by_actor_id, "
                f"archived_at FROM {STRATEGY_DOCS_TABLE} "
                "WHERE project_id = %s AND archived_at IS NULL",
                (project_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                f"SELECT slug, content, updated_at, updated_by_actor_id, "
                f"archived_at FROM {STRATEGY_DOCS_TABLE} "
                "WHERE project_id = %s",
                (project_id,),
            ).fetchall()
        rows_by_slug = {}
        for row in rows:
            actor = row["updated_by_actor_id"]
            archived_at = row["archived_at"]
            slug = str(row["slug"])
            rows_by_slug[slug] = {
                "slug": slug,
                "content": str(row["content"]),
                "updated_at": str(row["updated_at"]),
                "updated_by_actor_id": int(actor) if actor is not None else None,
                "archived_at": str(archived_at) if archived_at is not None else None,
            }
        ordered = tuple(slug for slug in ordered if slug in rows_by_slug)
    if not ordered:
        raise StrategyDocMissingError(
            missing_doc_teaching(conn, project_id, "<any>")
        )
    files: List[Dict[str, Any]] = []
    for slug in ordered:
        doc = rows_by_slug[slug]
        body = str(doc["content"])
        archived = doc.get("archived_at") is not None
        digest = content_sha256(body)
        entry: Dict[str, Any] = {
            "slug": slug,
            "updated_at": doc["updated_at"],
            "archived": archived,
            "content_sha256": digest,
            "bytes": len(body.encode("utf-8")),
        }
        cached = known_map.get(slug)
        if cached is not None and _row_matches_known(doc, cached):
            entry["unchanged"] = True
            files.append(entry)
            continue
        updated_by = render_actor_name(conn, doc.get("updated_by_actor_id"))
        entry["unchanged"] = False
        entry["file_text"] = render_file_text(
            slug, doc["updated_at"], body, updated_by=updated_by,
        )
        files.append(entry)
    return files


__all__ = [
    "render_file_map",
    "write_rendered_files",
]
