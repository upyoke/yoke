"""Architecture health: coverage and violations computed from the map.

One computer shared by every reader — the Doctor architecture checks,
the board's architecture section, and the dashboard read surface — so
"architecture health" has a single definition: whatever the project's
declared map covers, plus how much of the tree carries a
classification. Findings are returned as structured tuples; callers
own message shaping and severity.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Mapping, Optional, Tuple

from yoke_core.domain.architecture_context_data import (
    iter_python_entries,
    load_architecture_context,
    load_architecture_model,
    load_module_target_index,
    module_to_target_id_from_index,
    package_roots_from_model,
)
from yoke_core.domain.architecture_model import derive_edges


UnclassifiedFinding = Tuple[int, str]
ForbiddenEdgeFinding = Tuple[str, str, str, str]
CrossCuttingFinding = Tuple[str, str, str, List[str]]


def unclassified_paths(
    conn: Any, project_id: str | int, *, model: Mapping[str, Any],
) -> List[UnclassifiedFinding]:
    """Python paths with no inherited layer/domain and no exemption."""
    findings: List[UnclassifiedFinding] = []
    entries = iter_python_entries(conn, project_id)
    contexts = load_architecture_context(
        conn, (target_id for target_id, _path, _mod, _deps in entries),
    )
    for target_id, path, _mod, _deps in entries:
        context = contexts.get(target_id, {})
        if context.get("exempt"):
            continue
        if context.get("layer") is not None:
            continue
        if context.get("domain") is not None:
            continue
        findings.append((target_id, path))
    return findings


def forbidden_edge_violations(
    conn: Any, project_id: str | int, *, model: Mapping[str, Any],
) -> List[ForbiddenEdgeFinding]:
    """Recorded dependency edges the layer rules forbid or omit.

    Each finding is ``(path, source_layer, imported_layer,
    imported_module)``.
    """
    allowed_edges, forbidden_edges = derive_edges(model)
    package_roots = package_roots_from_model(model)
    entries = iter_python_entries(conn, project_id)
    module_index = load_module_target_index(conn, project_id)
    parsed_entries = []
    context_ids = {target_id for target_id, _path, _mod, _deps in entries}
    for target_id, path, _mod, deps_text in entries:
        try:
            edges = json.loads(deps_text)
        except (TypeError, ValueError):
            continue
        parsed_entries.append((target_id, path, edges))
        for edge in edges:
            if not isinstance(edge, Mapping):
                continue
            imp_target = module_to_target_id_from_index(
                module_index,
                str(edge.get("imported_module", "")),
                str(edge.get("imported_name", "")),
                package_roots=package_roots,
            )
            if imp_target is not None:
                context_ids.add(imp_target)
    contexts = load_architecture_context(conn, context_ids)
    findings: List[ForbiddenEdgeFinding] = []
    for target_id, path, edges in parsed_entries:
        source_layer = contexts.get(target_id, {}).get("layer")
        if source_layer is None:
            continue
        for edge in edges:
            if not isinstance(edge, Mapping):
                continue
            imp_module = str(edge.get("imported_module", ""))
            imp_name = str(edge.get("imported_name", ""))
            imp_target = module_to_target_id_from_index(
                module_index, imp_module, imp_name,
                package_roots=package_roots,
            )
            if imp_target is None:
                continue
            imp_layer = contexts.get(imp_target, {}).get("layer")
            if imp_layer is None or imp_layer == source_layer:
                continue
            pair = (source_layer, imp_layer)
            if pair in forbidden_edges or pair not in allowed_edges:
                findings.append((path, source_layer, imp_layer, imp_module))
    return findings


def _guarded_index(
    model: Mapping[str, Any],
) -> List[Tuple[str, str, str, List[str], List[str]]]:
    """Flatten ``cross_cutting_entrypoints[*].guarded_imports`` into
    ``(ep_name, module, symbol, approved_modules, approved_prefixes)``
    tuples."""
    entries: List[Tuple[str, str, str, List[str], List[str]]] = []
    entrypoints = model.get("cross_cutting_entrypoints") or {}
    for ep_name, ep_value in entrypoints.items():
        if not isinstance(ep_value, Mapping):
            continue
        approved = list(ep_value.get("approved_modules") or [])
        prefixes = list(ep_value.get("approved_module_prefixes") or [])
        guarded = ep_value.get("guarded_imports") or []
        for guard in guarded:
            if not isinstance(guard, str) or "." not in guard:
                continue
            mod, _, name = guard.rpartition(".")
            entries.append((ep_name, mod, name, approved, prefixes))
    return entries


def cross_cutting_violations(
    conn: Any, project_id: str | int, *, model: Mapping[str, Any],
) -> List[CrossCuttingFinding]:
    """Direct imports of guarded symbols outside the approved modules.

    Each finding is ``(path, entrypoint, guarded_symbol,
    approved_modules)``.
    """
    guarded = _guarded_index(model)
    if not guarded:
        return []
    findings: List[CrossCuttingFinding] = []
    for _tid, path, source_module, deps_text in iter_python_entries(
        conn, project_id,
    ):
        try:
            edges = json.loads(deps_text)
        except (TypeError, ValueError):
            continue
        for ep_name, g_mod, g_name, approved, prefixes in guarded:
            if source_module in approved:
                continue
            if any(source_module.startswith(p) for p in prefixes):
                continue
            for edge in edges:
                if not isinstance(edge, Mapping):
                    continue
                if (edge.get("imported_module") == g_mod
                        and edge.get("imported_name") == g_name):
                    findings.append(
                        (path, ep_name, f"{g_mod}.{g_name}", approved)
                    )
    return findings


EXAMPLE_LIMIT = 10


def compute_architecture_health(
    conn: Any, project_id: str | int,
) -> Dict[str, Any]:
    """Aggregate map summary, classification coverage, and violations.

    ``{"declared": False}`` when the project declares no map. Coverage
    counts every Python path in the latest snapshot as classified
    (inherits a layer or domain), exempt, or unclassified.
    """
    model: Optional[Dict[str, Any]] = load_architecture_model(
        conn, project_id,
    )
    if model is None:
        return {"declared": False}
    entries = iter_python_entries(conn, project_id)
    contexts = load_architecture_context(
        conn, (target_id for target_id, _path, _mod, _deps in entries),
    )
    classified = exempt = unclassified = 0
    for target_id, _path, _mod, _deps in entries:
        context = contexts.get(target_id, {})
        if context.get("exempt"):
            exempt += 1
        elif context.get("layer") or context.get("domain"):
            classified += 1
        else:
            unclassified += 1
    total = len(entries)
    covered = classified + exempt
    forbidden = forbidden_edge_violations(conn, project_id, model=model)
    cross_cutting = cross_cutting_violations(conn, project_id, model=model)
    return {
        "declared": True,
        "python_paths": total,
        "classified": classified,
        "exempt": exempt,
        "unclassified": unclassified,
        "coverage_pct": round(100.0 * covered / total, 1) if total else 0.0,
        "forbidden_edge_count": len(forbidden),
        "cross_cutting_count": len(cross_cutting),
        "forbidden_edge_examples": [
            {
                "path": path,
                "source_layer": source,
                "imported_layer": imported,
                "imported_module": module,
            }
            for path, source, imported, module in forbidden[:EXAMPLE_LIMIT]
        ],
        "cross_cutting_examples": [
            {
                "path": path,
                "entrypoint": entrypoint,
                "guarded_symbol": symbol,
            }
            for path, entrypoint, symbol, _approved
            in cross_cutting[:EXAMPLE_LIMIT]
        ],
        "layers": [
            {
                "id": layer.get("id"),
                "may_depend_on": list(layer.get("may_depend_on") or []),
                "forbidden_edges": list(layer.get("forbidden_edges") or []),
            }
            for layer in model.get("layers") or []
        ],
        "domains": [
            {
                "id": domain.get("id"),
                "pattern_count": len(domain.get("path_roots") or []),
            }
            for domain in model.get("domains") or []
        ],
        "entrypoints": sorted(
            (model.get("cross_cutting_entrypoints") or {}).keys()
        ),
        "exemption_patterns": len(model.get("exemptions") or []),
    }


__all__ = [
    "EXAMPLE_LIMIT",
    "CrossCuttingFinding",
    "ForbiddenEdgeFinding",
    "UnclassifiedFinding",
    "compute_architecture_health",
    "cross_cutting_violations",
    "forbidden_edge_violations",
    "unclassified_paths",
]
