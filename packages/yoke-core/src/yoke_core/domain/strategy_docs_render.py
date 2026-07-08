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

from typing import Any, Dict, List, Optional, Sequence

from yoke_contracts.project_contract.strategy_docs_header import render_file_text
from yoke_contracts.project_contract.strategy_docs_io import write_rendered_files


def render_file_map(
    conn: Any,
    project_id: int,
    slugs: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    """Return ``[{slug, updated_at, file_text, archived}]`` for the docs.

    ``file_text`` is the complete rendered file (idempotent header line
    + DB content) — exactly what belongs on disk. ``archived`` carries the
    doc's archived state so the writer routes it into
    ``.yoke/strategy/archive/`` and prunes the stale sibling on a flip.
    ``slugs`` narrows to a subset; ``None`` maps the full corpus. A
    project with zero rows
    raises :class:`yoke_core.domain.strategy_docs.StrategyDocMissingError`
    teaching the seed-defaults cold start. Surfaces
    :class:`yoke_core.domain.strategy_docs_header.StrategyHeaderError`
    (``kind="content_has_header"``) from :func:`render_file_text` when a
    row's ``content`` is itself a rendered file — the render boundary
    refuses to stack a second header rather than emit a corrupt view.
    """
    from yoke_core.domain.strategy_docs import (
        StrategyDocMissingError,
        _require_valid_slug,
        get_doc,
        missing_doc_teaching,
        project_doc_slugs,
    )

    from yoke_core.domain.actor_render import actor_render_label

    wanted = tuple(slugs) if slugs else tuple(project_doc_slugs(conn, project_id))
    if not wanted:
        raise StrategyDocMissingError(
            missing_doc_teaching(conn, project_id, "<any>")
        )
    files: List[Dict[str, Any]] = []
    for slug in wanted:
        _require_valid_slug(slug)
        doc = get_doc(conn, project_id, slug)
        # Resolve the editor's actor id to a display label (fail-open): the id
        # is the durable stored identity, the label is render-time only.
        updated_by = actor_render_label(conn, doc.get("updated_by_actor_id"))
        files.append(
            {
                "slug": slug,
                "updated_at": doc["updated_at"],
                "file_text": render_file_text(
                    slug, doc["updated_at"], doc["content"],
                    updated_by=updated_by,
                ),
                "archived": doc.get("archived_at") is not None,
            }
        )
    return files


__all__ = [
    "render_file_map",
    "write_rendered_files",
]
