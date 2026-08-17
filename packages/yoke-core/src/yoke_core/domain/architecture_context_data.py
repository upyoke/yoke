"""Data access for architecture-map evaluation.

Domain-level readers shared by the architecture health computer, the
context seeder, and the Doctor architecture checks: the model payload,
the latest snapshot's Python entries, inherited path context, and
module-to-path resolution driven by the model's declared
``package_roots`` layouts. Lives in the domain layer so service
handlers and board data may consume architecture facts without
importing engine orchestration.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from yoke_core.domain.path_context import (
    ARCHITECTURE_EXEMPTION_FAMILIES,
    FAMILY_ARCHITECTURE_DOMAIN,
    FAMILY_ARCHITECTURE_LAYER,
)
from yoke_core.domain.project_identity import resolve_project
from yoke_core.domain.schema_common import _table_exists


_SLASH = chr(47)

# ``{package: ((root, layout), ...)}`` parsed from the model payload's
# ``package_roots`` section. ``package_under_root`` roots contain the
# package directory (src layout); ``package_is_root`` roots ARE the
# package directory, so the package name is dropped from the path.
PackageRoots = Mapping[str, Tuple[Tuple[str, str], ...]]


def _p(conn: Any) -> str:
    from yoke_core.domain import db_backend
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def resolve_project_numeric(
    conn: Any, project_id: str | int, *, required: bool = True,
) -> Optional[int]:
    """Resolve a project id or slug to the numeric ``projects.id``."""
    if isinstance(project_id, int) or str(project_id).isdigit():
        return int(project_id)
    identity = resolve_project(conn, project_id, required=required)
    return identity.id if identity is not None else None


def load_architecture_model(
    conn: Any, project_id: str | int,
) -> Optional[Dict[str, Any]]:
    """Return the project's ``architecture_model`` singleton payload, or
    None when absent / malformed / table missing."""
    if not _table_exists(conn, "project_structure"):
        return None
    numeric_project_id = resolve_project_numeric(
        conn, project_id, required=False,
    )
    if numeric_project_id is None:
        return None
    row = conn.execute(
        f"SELECT payload FROM project_structure "
        f"WHERE project_id = {_p(conn)} AND family = 'architecture_model'",
        (numeric_project_id,),
    ).fetchone()
    if row is None or row[0] is None:
        return None
    try:
        payload = json.loads(row[0])
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def package_roots_from_model(
    model: Optional[Mapping[str, Any]],
) -> PackageRoots:
    """Parse the model's declared package-layout mapping.

    Absent or malformed sections yield an empty mapping, which degrades
    module resolution to the naive dotted-path candidate only.
    """
    raw = (model or {}).get("package_roots")
    if not isinstance(raw, Mapping):
        return {}
    parsed: Dict[str, Tuple[Tuple[str, str], ...]] = {}
    for package, entries in raw.items():
        if not isinstance(package, str) or not isinstance(entries, list):
            continue
        pairs = tuple(
            (str(entry["root"]), str(entry["layout"]))
            for entry in entries
            if isinstance(entry, Mapping)
            and entry.get("root")
            and entry.get("layout")
        )
        if pairs:
            parsed[package] = pairs
    return parsed


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
    "exempt": bool}}``. Mirrors the nearest-ancestor behavior of
    per-target context reads, but in one recursive query so callers
    stay usable against remote Postgres.
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
    numeric_project_id = resolve_project_numeric(conn, project_id)
    rows = conn.execute(
        f"SELECT path_string, id FROM path_targets "
        f"WHERE project_id = {p} AND kind = 'file'",
        (numeric_project_id,),
    ).fetchall()
    return {str(row[0]): int(row[1]) for row in rows}


def module_to_target_id_from_index(
    index: Dict[str, int], module_name: str, imported_name: str = "",
    *, package_roots: PackageRoots,
) -> Optional[int]:
    """Resolve a dotted module name through a preloaded path index."""
    candidates = _candidate_paths_for_module(
        module_name, imported_name, package_roots=package_roots,
    )
    for path in candidates:
        found = index.get(path)
        if found is not None:
            return found
    return None


def _candidate_paths_for_module(
    module_name: str, imported_name: str = "",
    *, package_roots: PackageRoots,
) -> Tuple[str, ...]:
    """Return path candidates for a module from the declared layouts."""
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
        for root, layout in package_roots.get(parts[0], ()):
            if layout == "package_is_root":
                bare_stem = _SLASH.join(parts[1:])
                if bare_stem:
                    add(root + _SLASH + bare_stem)
            else:
                add(root + _SLASH + package_stem)
    return tuple(paths)


def module_to_target_id(
    conn: Any, project_id: str | int, module_name: str,
    imported_name: str = "",
    *, package_roots: PackageRoots,
) -> Optional[int]:
    """Resolve a dotted module name to its observed ``path_targets.id``.

    Returns None for external modules (``json``, ``sqlite3``) or for
    project-internal modules not present in path_targets yet.
    """
    path_candidates = _candidate_paths_for_module(
        module_name, imported_name, package_roots=package_roots,
    )
    if not path_candidates:
        return None
    p = _p(conn)
    placeholders = ",".join(p for _ in path_candidates)
    numeric_project_id = resolve_project_numeric(conn, project_id)
    row = conn.execute(
        f"SELECT id FROM path_targets WHERE project_id = {p} "
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
    p = _p(conn)
    numeric_project_id = resolve_project_numeric(conn, project_id)
    rows = conn.execute(
        "SELECT pse.target_id, pt.path_string, pse.module_name, "
        "       pse.dependency_edges "
        "FROM path_snapshot_entries pse "
        "JOIN path_snapshots ps ON ps.id = pse.snapshot_id "
        "JOIN path_targets pt ON pt.id = pse.target_id "
        f"WHERE ps.project_id = {p} AND pse.language = 'python' "
        "AND ps.id = ("
        "  SELECT id FROM path_snapshots "
        f"  WHERE project_id = {p} ORDER BY id DESC LIMIT 1"
        ")",
        (numeric_project_id, numeric_project_id),
    ).fetchall()
    return [(int(r[0]), str(r[1]), str(r[2] or ""), str(r[3] or "[]"))
            for r in rows]


__all__ = [
    "PackageRoots",
    "iter_python_entries",
    "load_architecture_context",
    "load_architecture_model",
    "load_module_target_index",
    "module_to_target_id",
    "module_to_target_id_from_index",
    "package_roots_from_model",
    "resolve_project_numeric",
]
