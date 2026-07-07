"""Shared helpers for the architecture-fitness Doctor HCs.

Carved out of :mod:`yoke_core.engines.doctor_hc_architecture` so the
parent HC module stays under the 350-line authored-file cap. Public
surface is private (underscore prefix); the HC modules are the only
intended consumers.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional, Tuple

import yoke_core.engines.doctor_report as _base

from yoke_core.domain.path_context import (
    ARCHITECTURE_EXEMPTION_FAMILIES,
    FAMILY_ARCHITECTURE_DOMAIN,
    FAMILY_ARCHITECTURE_LAYER,
    read_context_value,
)
from yoke_core.domain.project_identity import resolve_project_id


LIST_PREVIEW = 10
_SLASH = chr(47)
_PACKAGE_ROOTS: Dict[str, Tuple[str, ...]] = {
    "yoke_contracts": ("packages/yoke-contracts/src",),
    "yoke_cli": ("packages/yoke-cli/src",),
    "yoke_core": ("packages/yoke-core/src", "runtime/api"),
    "yoke_harness": ("packages/yoke-harness/src", "runtime/harness"),
}


def _resolve_project(conn: Any, project_id: str | int) -> int:
    if isinstance(project_id, int) or str(project_id).isdigit():
        return int(project_id)
    return resolve_project_id(conn, project_id)


def load_architecture_model(
    conn: Any, project_id: str | int,
) -> Optional[Dict[str, Any]]:
    """Return the project's ``architecture_model`` singleton payload, or
    None when absent / malformed / table missing."""
    if not _base._table_exists(conn, "project_structure"):
        return None
    numeric_project_id = _resolve_project(conn, project_id)
    row = conn.execute(
        "SELECT payload FROM project_structure "
        "WHERE project_id = %s AND family = 'architecture_model'",
        (numeric_project_id,),
    ).fetchone()
    if row is None or row[0] is None:
        return None
    try:
        payload = json.loads(row[0])
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _p(conn) -> str:
    from yoke_core.domain import db_backend
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _decode_context_value(value_text: Any) -> Dict[str, Any]:
    try:
        parsed = json.loads(value_text or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def load_architecture_context(
    conn: Any, target_ids: Iterable[int],
) -> Dict[int, Dict[str, Any]]:
    """Batch-load inherited architecture context for ``target_ids``.

    Returns ``{target_id: {"layer": str|None, "domain": str|None,
    "exempt": bool}}``. This mirrors the nearest-ancestor behavior used
    by ``read_context_value`` for the architecture families, but does it
    in one recursive query so Doctor's architecture HCs stay usable
    against remote Postgres.
    """
    ids = sorted({int(tid) for tid in target_ids})
    out: Dict[int, Dict[str, Any]] = {
        tid: {"layer": None, "domain": None, "exempt": False}
        for tid in ids
    }
    if not ids:
        return out
    families = (
        FAMILY_ARCHITECTURE_LAYER,
        FAMILY_ARCHITECTURE_DOMAIN,
        *tuple(ARCHITECTURE_EXEMPTION_FAMILIES),
    )
    p = _p(conn)
    id_placeholders = ",".join(p for _ in ids)
    family_placeholders = ",".join(p for _ in families)
    rows = conn.execute(
        "WITH RECURSIVE chain(target_id, ancestor_id, depth) AS ("
        f"  SELECT id, id, 0 FROM path_targets WHERE id IN ({id_placeholders}) "
        "  UNION ALL "
        "  SELECT chain.target_id, pt.parent_target_id, chain.depth + 1 "
        "  FROM chain "
        "  JOIN path_targets pt ON pt.id = chain.ancestor_id "
        "  WHERE pt.parent_target_id IS NOT NULL"
        ") "
        "SELECT chain.target_id, chain.depth, cv.context_family, cv.value "
        "FROM chain "
        "JOIN path_context_values cv ON cv.target_id = chain.ancestor_id "
        "WHERE cv.entry_key = '' "
        f"AND cv.context_family IN ({family_placeholders}) "
        "ORDER BY chain.target_id, cv.context_family, chain.depth",
        (*ids, *families),
    ).fetchall()
    seen_depth: Dict[Tuple[int, str], int] = {}
    for row in rows:
        target_id = int(row[0])
        depth = int(row[1])
        family = str(row[2])
        key = (target_id, family)
        if key in seen_depth and seen_depth[key] != depth:
            continue
        seen_depth.setdefault(key, depth)
        value = _decode_context_value(row[3])
        if family == FAMILY_ARCHITECTURE_LAYER:
            layer = value.get("layer")
            if isinstance(layer, str) and layer.strip():
                out[target_id]["layer"] = layer.strip()
        elif family == FAMILY_ARCHITECTURE_DOMAIN:
            domain = value.get("domain")
            if isinstance(domain, str) and domain.strip():
                out[target_id]["domain"] = domain.strip()
        elif family in ARCHITECTURE_EXEMPTION_FAMILIES and value:
            out[target_id]["exempt"] = True
    return out


def load_module_target_index(
    conn: Any, project_id: str | int,
) -> Dict[str, int]:
    """Return ``path_string -> path_targets.id`` for project files."""
    p = _p(conn)
    numeric_project_id = _resolve_project(conn, project_id)
    rows = conn.execute(
        f"SELECT path_string, id FROM path_targets "
        f"WHERE project_id = {p} AND kind = 'file'",
        (numeric_project_id,),
    ).fetchall()
    return {str(row[0]): int(row[1]) for row in rows}


def module_to_target_id_from_index(
    index: Dict[str, int], module_name: str, imported_name: str = "",
) -> Optional[int]:
    """Resolve a dotted module name through a preloaded path index."""
    for path in _candidate_paths_for_module(module_name, imported_name):
        found = index.get(path)
        if found is not None:
            return found
    return None


def _candidate_paths_for_module(
    module_name: str, imported_name: str = "",
) -> Tuple[str, ...]:
    """Return package and synthetic-fixture path candidates for a module."""
    if not module_name:
        return ()
    modules = [module_name]
    if imported_name and imported_name != "*":
        modules.append(f"{module_name}.{imported_name}")

    paths: List[str] = []
    seen: set[str] = set()

    def add(stem: str) -> None:
        for path in (stem + ".py", _SLASH.join((stem, "__init__.py"))):
            if path not in seen:
                seen.add(path)
                paths.append(path)

    for candidate in modules:
        parts = candidate.split(".")
        package_stem = _SLASH.join(parts)
        add(package_stem)
        roots = _PACKAGE_ROOTS.get(parts[0], ())
        for root in roots:
            if root.startswith("runtime/"):
                legacy_stem = _SLASH.join(parts[1:])
                if legacy_stem:
                    add(root + _SLASH + legacy_stem)
            else:
                add(root + _SLASH + package_stem)
    return tuple(paths)


def path_in_exemption_family(
    conn: Any, target_id: int,
) -> bool:
    for family in ARCHITECTURE_EXEMPTION_FAMILIES:
        value = read_context_value(
            conn, target_id=target_id, context_family=family, entry_key="",
        )
        if isinstance(value, dict) and value:
            return True
    return False


def path_layer(
    conn: Any, target_id: int,
) -> Optional[str]:
    value = read_context_value(
        conn, target_id=target_id,
        context_family=FAMILY_ARCHITECTURE_LAYER, entry_key="",
    )
    if isinstance(value, dict) and isinstance(value.get("layer"), str):
        return str(value["layer"]).strip() or None
    return None


def path_domain(
    conn: Any, target_id: int,
) -> Optional[str]:
    value = read_context_value(
        conn, target_id=target_id,
        context_family=FAMILY_ARCHITECTURE_DOMAIN, entry_key="",
    )
    if isinstance(value, dict) and isinstance(value.get("domain"), str):
        return str(value["domain"]).strip() or None
    return None


def module_to_target_id(
    conn: Any, project_id: str | int, module_name: str,
    imported_name: str = "",
) -> Optional[int]:
    """Resolve a dotted module name to its observed ``path_targets.id``.

    Returns None for external modules (``json``, ``sqlite3``) or for
    project-internal modules not present in path_targets yet.
    """
    path_candidates = _candidate_paths_for_module(module_name, imported_name)
    if not path_candidates:
        return None
    placeholders = ",".join("%s" for _ in path_candidates)
    numeric_project_id = _resolve_project(conn, project_id)
    row = conn.execute(
        f"SELECT id FROM path_targets WHERE project_id = %s "
        f"AND kind = 'file' AND path_string IN ({placeholders})",
        (numeric_project_id, *path_candidates),
    ).fetchone()
    return int(row[0]) if row else None


def iter_python_entries(
    conn: Any, project_id: str | int,
) -> List[Tuple[int, str, str, str]]:
    """Yield ``(target_id, path_string, module_name, dependency_edges)``
    for each ``language='python'`` snapshot entry in the project's
    latest HEAD snapshot."""
    numeric_project_id = _resolve_project(conn, project_id)
    rows = conn.execute(
        "SELECT pse.target_id, pt.path_string, pse.module_name, "
        "       pse.dependency_edges "
        "FROM path_snapshot_entries pse "
        "JOIN path_snapshots ps ON ps.id = pse.snapshot_id "
        "JOIN path_targets pt ON pt.id = pse.target_id "
        "WHERE ps.project_id = %s AND pse.language = 'python' "
        "AND ps.id = ("
        "  SELECT id FROM path_snapshots "
        "  WHERE project_id = %s ORDER BY id DESC LIMIT 1"
        ")",
        (numeric_project_id, numeric_project_id),
    ).fetchall()
    return [(int(r[0]), str(r[1]), str(r[2] or ""), str(r[3] or "[]"))
            for r in rows]


def format_findings(head: str, findings: List[str]) -> str:
    """Build the HC `detail` string from a header line + finding list.
    Truncates to :data:`LIST_PREVIEW` entries with a trailing summary."""
    tail: List[str] = []
    if len(findings) > LIST_PREVIEW:
        tail = [f"  ... and {len(findings) - LIST_PREVIEW} more"]
    return "\n".join([head] + findings[:LIST_PREVIEW] + tail)


__all__ = [
    "LIST_PREVIEW",
    "format_findings",
    "iter_python_entries",
    "load_architecture_context",
    "load_architecture_model",
    "load_module_target_index",
    "module_to_target_id",
    "module_to_target_id_from_index",
    "path_domain",
    "path_in_exemption_family",
    "path_layer",
]
