"""Strategy-file delivery for ``yoke project install`` — server half.

:func:`bundle_strategy_files` renders the bundle's ``strategy_files``
section from the project's ``strategy_docs`` rows, cold-starting the
default placeholder corpus first when the project has zero rows — a
fresh external install always receives a starter corpus. The row→text
rendering delegates to the shared
:func:`yoke_core.domain.strategy_docs_render.render_file_map`, so the
bundle inherits exactly the same header, ``updated_by`` resolution, and
archived-doc routing as ``yoke strategy render`` — there is no second
copy of the render logic. Entries carry the full rendered file
(idempotent YOKE:STRATEGY-DOC header + body) so the client can use the
header/CAS machinery.

The client half — the seed/preserve-uningested-edits apply pass and its
manifest bookkeeping — lives in
:mod:`yoke_cli.project_install.strategy` (the copy the install runner
imports); it is deliberately not duplicated here.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List

from yoke_core.domain.strategy_docs_paths import (
    slug_from_view_path,
    strategy_view_rel_path,
)

# The one install policy this ownership class understands.
STRATEGY_INSTALL_POLICY = "db_render"


def bundle_strategy_files(
    conn: Any, project_id: int, display_name: str,
) -> List[Dict[str, str]]:
    """Render the ``strategy_files`` bundle section from the DB rows.

    Cold-start: a project with zero strategy rows gets the default
    placeholder corpus seeded first (DB-first; files always render FROM
    rows). The render itself is the shared ``render_file_map``, so an
    archived doc routes to its ``.yoke/strategy/archive/<slug>.md`` path
    and every doc carries the resolved ``updated_by`` header — identical
    bytes to ``yoke strategy render``.
    """
    from yoke_core.domain.strategy_docs_defaults import seed_default_docs
    from yoke_core.domain.strategy_docs_render import render_file_map

    seed_default_docs(conn, project_id, display_name)
    entries = [
        {
            "path": strategy_view_rel_path(entry["slug"], entry["archived"]),
            "content": entry["file_text"],
            "install_policy": STRATEGY_INSTALL_POLICY,
        }
        for entry in render_file_map(conn, project_id)
    ]
    entries.sort(key=lambda entry: entry["path"])
    return entries


def assert_safe_strategy_paths(paths: Iterable[str]) -> None:
    """Refuse strategy entries outside ``.yoke/strategy/[archive/]<slug>.md``.

    ``slug_from_view_path`` accepts both the active and the ``archive/``
    locations, so archived-doc bundle entries pass while any more deeply
    nested or non-``.md`` path is rejected.
    """
    from yoke_core.domain.project_install_files import ProjectInstallError

    for raw in paths:
        if slug_from_view_path(str(raw)) is None:
            raise ProjectInstallError(
                f"bundle names an unsafe strategy path {raw!r}: strategy "
                "entries must be .yoke/strategy/<slug>.md rendered views "
                "(archived docs at .yoke/strategy/archive/<slug>.md)"
            )


__all__ = [
    "STRATEGY_INSTALL_POLICY",
    "assert_safe_strategy_paths",
    "bundle_strategy_files",
]
