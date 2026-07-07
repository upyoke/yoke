"""Compute architecture-fitness enrichment columns for path snapshots.

Pure functions plus one DB-aware orchestrator that produces values for
the six ``path_snapshot_entries`` enrichment columns:

* ``line_count`` — newline-counted line count of the file text.
* ``language`` — well-known language label inferred from extension
  (``python`` / ``markdown`` / ``json`` / ``yaml`` / ``shell`` /
  ``javascript`` / ``typescript`` / ``html`` / ``css`` / ``sql``).
  Unknown extensions return ``None``.
* ``module_name`` — dotted module name for ``.py`` files (delegates to
  :func:`yoke_core.domain.architecture_dependency_scan.path_to_module`).
  Non-Python files return ``None``.
* ``area`` — inherited from the existing ``posture`` context family's
  ``area`` key, when assigned by Project Structure mappings. Falls back
  to ``None``; the architecture HCs do not require ``area`` to fire.
* ``is_generated`` — 1 when the path inherits a non-empty value from
  ``architecture_generated`` context family, else 0.
* ``dependency_edges`` — JSON-encoded list of ``{source_module,
  imported_module, imported_name}`` for ``.py`` files; ``"[]"`` for
  non-Python. Python parse failures store one sentinel edge with a
  ``scan_error`` key so Doctor can report the path later.

The orchestrator never opens files. Callers (currently the snapshot
writer) read the project tree once and pass content in. This keeps the
enrichment helper independent of ``git``, the project's working copy,
and the snapshot transaction.

Parse / scan errors are surfaced via the returned ``scan_error`` field
rather than raised, so the Doctor scan keeps going even when one file
is malformed.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from yoke_contracts.path_snapshot import (
    compute_line_count as _contract_line_count,
    compute_module_name as _contract_module_name,
    extract_edges as _extract_edges,
    infer_language as _contract_language,
)
from yoke_core.domain.path_context import (
    FAMILY_GENERATED,
    FAMILY_POSTURE,
    read_context_value,
)
from yoke_core.domain.path_snapshot_context_cache import (
    SnapshotContextCache,
    build_snapshot_context_cache,
)

from yoke_core.domain import db_backend
from yoke_core.domain.path_registry import KIND_FILE


@dataclass(frozen=True)
class EnrichmentColumns:
    line_count: int
    language: Optional[str]
    module_name: Optional[str]
    area: Optional[str]
    is_generated: int
    dependency_edges: str
    scan_error: Optional[str] = None


def compute_line_count(source: str) -> int:
    """Count lines using ``splitlines()`` semantics.

    Empty content is ``0``. A trailing newline does not contribute an
    extra empty line. This matches what ``wc -l`` reports for typical
    POSIX text files within a few-line tolerance and is stable across
    platforms.
    """
    return _contract_line_count(source)


def infer_language(path_string: str) -> Optional[str]:
    """Return a well-known language label or ``None`` if the extension
    is not in the closed vocabulary."""
    return _contract_language(path_string)


def compute_module_name(path_string: str) -> Optional[str]:
    """Dotted module name for ``.py`` files; ``None`` otherwise."""
    return _contract_module_name(path_string)


def compute_dependency_edges(
    source: str, path_string: str,
) -> Dict[str, Any]:
    """Return ``{"edges": [...], "scan_error": Optional[str]}``.

    Non-Python files return an empty edge list and no error. Python
    files route through :func:`...architecture_dependency_scan.extract_edges`,
    which surfaces parse failures via the returned ``error`` field.
    """
    if not path_string.endswith(".py"):
        return {"edges": [], "scan_error": None}
    result = _extract_edges(source, path_string)
    return {"edges": result.edges, "scan_error": result.error}


def _read_inherited_area(
    conn: Any, target_id: int,
) -> Optional[str]:
    """Read inherited ``posture.area`` value (string) or ``None``."""
    value = read_context_value(
        conn,
        target_id=target_id,
        context_family=FAMILY_POSTURE,
        entry_key="area",
    )
    if value is None:
        return None
    area = value.get("area") if isinstance(value, dict) else None
    if isinstance(area, str) and area.strip():
        return area
    return None


def _read_inherited_generated(
    conn: Any, target_id: int,
) -> int:
    """Return ``1`` if the path inherits a non-empty
    ``architecture_generated`` value, else ``0``."""
    value = read_context_value(
        conn,
        target_id=target_id,
        context_family=FAMILY_GENERATED,
        entry_key="",
    )
    if value is None:
        return 0
    # Any non-empty mapping under the family marks the path generated.
    return 1 if isinstance(value, dict) and value else 0


def enrich_entry(
    conn: Any,
    *,
    target_id: int,
    source: str,
    path_string: str,
    context_cache: Optional[SnapshotContextCache] = None,
) -> EnrichmentColumns:
    """Compute the six enrichment columns for a single snapshot entry.

    The caller resolves ``source`` (the file's text) — typically via
    ``git show <commit>:<path>`` or a worktree read. The DB connection
    is used only to read inherited context values; the helper does not
    write to ``path_snapshot_entries`` (the snapshot writer owns the
    transaction).
    """
    deps = compute_dependency_edges(source, path_string)
    edges = deps["edges"]
    module_name = compute_module_name(path_string)
    if deps["scan_error"]:
        edges = [{
            "source_module": module_name or path_string,
            "imported_module": "",
            "imported_name": "",
            "scan_error": deps["scan_error"],
        }]
    return EnrichmentColumns(
        line_count=compute_line_count(source),
        language=infer_language(path_string),
        module_name=module_name,
        area=(
            context_cache.area_for(target_id)
            if context_cache is not None
            else _read_inherited_area(conn, target_id)
        ),
        is_generated=(
            context_cache.is_generated(target_id)
            if context_cache is not None
            else _read_inherited_generated(conn, target_id)
        ),
        dependency_edges=json.dumps(edges, sort_keys=True),
        scan_error=deps["scan_error"],
    )


def as_db_tuple(cols: EnrichmentColumns) -> tuple:
    """Return ``(line_count, language, module_name, area, is_generated,
    dependency_edges)`` in column order for an executemany INSERT."""
    return (
        cols.line_count,
        cols.language,
        cols.module_name,
        cols.area,
        cols.is_generated,
        cols.dependency_edges,
    )


_DEFAULT_DIRECTORY_TUPLE: Tuple = (None, None, None, None, 0, "[]")


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _executemany(conn: Any, sql: str, rows: List[Tuple]) -> None:
    if db_backend.connection_is_postgres(conn):
        with getattr(conn, "_inner", conn).cursor() as cur:
            cur.executemany(sql, rows)
        return
    conn.executemany(sql, rows)


def _read_file_at_commit(
    repo_path: Path, commit_sha: str, path_string: str,
) -> str:
    """Return the UTF-8 decoded file text at ``commit_sha:path_string``.

    Returns the empty string when the blob is missing, unreadable, or
    not UTF-8 — enrichment columns degrade gracefully to file-shape
    defaults rather than raising from inside the snapshot transaction.
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_path), "show",
             f"{commit_sha}:{path_string}"],
            capture_output=True, check=False,
        )
        if proc.returncode != 0:
            return ""
        try:
            return proc.stdout.decode("utf-8")
        except UnicodeDecodeError:
            return ""
    except Exception:
        return ""


def write_entries(
    conn: Any,
    *,
    snapshot_id: int,
    repo_path: Path,
    commit_sha: str,
    targets: List[Tuple[str, str]],
    target_ids: Dict[str, int],
) -> None:
    """Compute enrichment columns and insert ``path_snapshot_entries``.

    Files (``kind == 'file'``) read content via ``git show
    <commit>:<path>`` and route through :func:`enrich_entry`.
    Directories are inserted with the DDL defaults (``is_generated=0``,
    ``dependency_edges='[]'``, other columns ``NULL``).

    The caller owns the surrounding transaction; this helper performs
    only the entry INSERTs plus the per-file ``git show`` reads.
    """
    rows: List[Tuple] = []
    context_cache = build_snapshot_context_cache(
        conn, targets=targets, target_ids=target_ids,
    )
    for path_string, kind in targets:
        target_id = target_ids[path_string]
        if kind == KIND_FILE:
            source = _read_file_at_commit(
                repo_path, commit_sha, path_string,
            )
            cols = enrich_entry(
                conn,
                target_id=target_id,
                source=source,
                path_string=path_string,
                context_cache=context_cache,
            )
            rows.append((snapshot_id, target_id, *as_db_tuple(cols)))
        else:
            rows.append((snapshot_id, target_id) + _DEFAULT_DIRECTORY_TUPLE)
    p = _p(conn)
    _executemany(
        conn,
        "INSERT INTO path_snapshot_entries (snapshot_id, target_id, "
        "line_count, language, module_name, area, is_generated, "
        f"dependency_edges) VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})",
        rows,
    )


__all__ = [
    "EnrichmentColumns",
    "as_db_tuple",
    "compute_dependency_edges",
    "compute_line_count",
    "compute_module_name",
    "enrich_entry",
    "infer_language",
    "write_entries",
]
