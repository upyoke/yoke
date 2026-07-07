"""Strategy-file delivery for ``yoke project install`` — both halves.

Server half (:func:`bundle_strategy_files`): render the bundle's
``strategy_files`` section from the project's ``strategy_docs`` rows,
cold-starting the default placeholder corpus first when the project has
zero rows — a fresh external install always receives a starter corpus.
Entries carry the full rendered file (idempotent YOKE:STRATEGY-DOC
header + body) so the client can use the header/CAS machinery.

Client half (:func:`apply_strategy_files`): a THIRD ownership class,
distinct from managed ``files`` (bundle is authority, pruned on
refresh/uninstall) and ``seed_if_missing`` contract files (write once,
never touch again):

* missing file → write;
* file present whose body still matches its own header hash (no
  un-ingested local edits) → overwrite with the new render — the DB is
  authority for rendered views;
* file present with un-ingested local edits (body hash ≠ header hash,
  or no parseable header) → preserve + warn — never clobber an edit
  that has not flowed back through ``yoke strategy ingest``;
* uninstall NEVER removes strategy files (planning content outlives
  the tooling) — there is deliberately no removal helper here.

Manifest bookkeeping lives under the ``strategy_files`` key (path →
sha256 of the last installer-written render); old manifests without the
key and old bundles without the section keep working (same optional-
field pattern as ``project_contract_files``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from yoke_core.domain.strategy_docs_header import (
    StrategyHeaderError,
    content_sha256,
    parse_file_text,
    render_file_text,
)
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
    rows). Backend-aware so the in-process sqlite bundle fixtures and
    the Postgres control plane both serve it.
    """
    from yoke_core.domain.strategy_docs import STRATEGY_DOCS_TABLE
    from yoke_core.domain.strategy_docs_defaults import seed_default_docs

    seed_default_docs(conn, project_id, display_name)
    p = _placeholder(conn)
    rows = conn.execute(
        f"SELECT slug, content, updated_at FROM {STRATEGY_DOCS_TABLE} "
        f"WHERE project_id = {p}",
        (project_id,),
    ).fetchall()
    entries = []
    for row in rows:
        slug, content, updated_at = _row_values(row)
        entries.append(
            {
                "path": strategy_view_rel_path(slug),
                "content": render_file_text(slug, updated_at, content),
                "install_policy": STRATEGY_INSTALL_POLICY,
            }
        )
    entries.sort(key=lambda entry: entry["path"])
    return entries


def assert_safe_strategy_paths(paths: Iterable[str]) -> None:
    """Refuse strategy entries outside ``.yoke/strategy/<slug>.md``."""
    from yoke_core.domain.project_install_files import ProjectInstallError

    for raw in paths:
        if slug_from_view_path(str(raw)) is None:
            raise ProjectInstallError(
                f"bundle names an unsafe strategy path {raw!r}: strategy "
                "entries must be flat .yoke/strategy/<slug>.md rendered "
                "views"
            )


def apply_strategy_files(
    repo_root: Path,
    entries: List[Dict[str, str]],
    old_map: Dict[str, str],
) -> Tuple[Dict[str, str], List[str], List[str], List[str], List[str]]:
    """DB-render pass over strategy entries.

    Returns ``(strategy_map, written, unchanged, preserved_edited,
    warnings)``. ``strategy_map`` records the sha256 of the last
    installer-written render per path; entries for preserved (edited)
    files carry their previous value forward so the bookkeeping never
    pretends the local edit came from the installer.
    """
    from yoke_core.domain.project_install_files import sha256_text

    strategy_map = dict(old_map)
    written: List[str] = []
    unchanged: List[str] = []
    preserved: List[str] = []
    warnings: List[str] = []
    for entry in entries:
        rel, content = entry["path"], entry["content"]
        target = repo_root / rel
        if target.is_file():
            try:
                current = target.read_bytes().decode("utf-8")
            except (OSError, UnicodeDecodeError):
                current = None
            if current is not None and current == content:
                strategy_map[rel] = sha256_text(content)
                unchanged.append(rel)
                continue
            if current is None or _has_uningested_edits(current):
                preserved.append(rel)
                warnings.append(
                    f"{rel} has local edits that never flowed back through "
                    "`yoke strategy ingest`; preserved — ingest (or "
                    "discard) the edit, then rerun `yoke project refresh`"
                )
                continue
            if _bodies_match(current, content):
                # Only the render header drifted (the DB row's updated_at can
                # advance on a no-op re-save) — the doc body is byte-identical.
                # Keep the committed view: a metadata-only bump must not churn a
                # clean tracked file. Record the on-disk sha so the manifest
                # tracks what is actually on disk.
                strategy_map[rel] = sha256_text(current)
                unchanged.append(rel)
                continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        strategy_map[rel] = sha256_text(content)
        written.append(rel)
    return strategy_map, written, unchanged, preserved, warnings


def _has_uningested_edits(file_text: str) -> bool:
    """True when a rendered view was hand-edited without write-back.

    A clean render's body hashes to its own header marker; anything
    else (changed body, missing/mangled header) is operator content the
    installer must not clobber.
    """
    try:
        header = parse_file_text(file_text)
    except StrategyHeaderError:
        return True
    return content_sha256(header.body) != header.content_sha256


def _bodies_match(current_text: str, new_text: str) -> bool:
    """True when two rendered views share a body, differing only in header.

    The render header carries the DB row's ``updated_at`` (and optional
    ``updated_by``), which advances on a no-op re-save while the body stays
    byte-identical. A body match means the only difference is metadata, so the
    installer keeps the committed file rather than churning it.
    """
    try:
        return parse_file_text(current_text).body == parse_file_text(new_text).body
    except StrategyHeaderError:
        return False


def _placeholder(conn: Any) -> str:
    from yoke_core.domain import db_backend

    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _row_values(row: Any) -> Tuple[str, str, str]:
    if hasattr(row, "keys"):
        return str(row["slug"]), str(row["content"]), str(row["updated_at"])
    return str(row[0]), str(row[1]), str(row[2])


__all__ = [
    "STRATEGY_INSTALL_POLICY",
    "apply_strategy_files",
    "assert_safe_strategy_paths",
    "bundle_strategy_files",
]
