"""Path-based architecture-fitness Doctor HCs.

Owns the three checks that read the project's latest HEAD snapshot:

* ``HC-architecture-unclassified-path`` — a snapshot path has no
  inherited ``architecture_layer`` / ``architecture_domain`` and is
  not covered by any exemption family.
* ``HC-architecture-forbidden-edge`` — a recorded dependency edge
  crosses a layer boundary the model forbids or omits from the
  source layer's ``may_depend_on`` list.
* ``HC-architecture-cross-cutting-entrypoint`` — a non-approved module
  imports a symbol the entrypoint's ``guarded_imports`` registry has
  marked as restricted (e.g. ``sqlite3.connect``).

Item-side checks (``HC-architecture-impact-declaration`` and
``HC-architecture-scan-error``) live in the sibling
:mod:`yoke_core.engines.doctor_hc_architecture_items`. The Doctor
registry exposes all five via
:mod:`yoke_core.engines.doctor_registry_architecture`.

All three checks degrade gracefully: missing tables, missing
``architecture_model`` rows, or empty snapshots all PASS rather than
raise.
"""

from __future__ import annotations

import json
from typing import List, Mapping, Tuple

import yoke_core.engines.doctor_report as _base
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector

from yoke_core.domain.architecture_model import derive_edges
from yoke_core.engines.doctor_hc_architecture_helpers import (
    format_findings,
    iter_python_entries,
    load_architecture_context,
    load_architecture_model,
    load_module_target_index,
    module_to_target_id_from_index,
)


_UNCLASSIFIED = "HC-architecture-unclassified-path"
_UNCLASSIFIED_DESC = "Observed path has no inherited architecture domain or layer"
_FORBIDDEN_EDGE = "HC-architecture-forbidden-edge"
_FORBIDDEN_EDGE_DESC = "Recorded dependency edge violates the architecture model"
_CROSS_CUTTING = "HC-architecture-cross-cutting-entrypoint"
_CROSS_CUTTING_DESC = "Non-approved module imports a guarded cross-cutting symbol"


def hc_architecture_unclassified_path(
    conn, args: DoctorArgs, rec: RecordCollector,
) -> None:
    if not _base._table_exists(conn, "path_snapshot_entries"):
        rec.record(_UNCLASSIFIED, _UNCLASSIFIED_DESC, "PASS",
                   "path_snapshot_entries missing — skipping")
        return
    model = load_architecture_model(conn, args.project)
    if model is None:
        rec.record(_UNCLASSIFIED, _UNCLASSIFIED_DESC, "PASS",
                   "architecture_model not set for project — skipping")
        return
    findings: List[str] = []
    entries = iter_python_entries(conn, args.project)
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
        findings.append(
            f"- {path} (target {target_id}) has no inherited "
            "architecture_layer / architecture_domain. Set one of "
            "{architecture_layer, architecture_domain} via "
            "path_context_values or mark the path with an exemption family."
        )
    if not findings:
        rec.record(_UNCLASSIFIED, _UNCLASSIFIED_DESC, "PASS", "")
        return
    head = (
        f"- {len(findings)} python path(s) lack architecture classification. "
        "Each must inherit an architecture_layer or architecture_domain, "
        "OR carry an exemption family (architecture_generated, "
        "architecture_fixture, architecture_archive, "
        "architecture_test_surface, architecture_template_managed)."
    )
    rec.record(_UNCLASSIFIED, _UNCLASSIFIED_DESC, "WARN",
               format_findings(head, findings))


def hc_architecture_forbidden_edge(
    conn, args: DoctorArgs, rec: RecordCollector,
) -> None:
    if not _base._table_exists(conn, "path_snapshot_entries"):
        rec.record(_FORBIDDEN_EDGE, _FORBIDDEN_EDGE_DESC, "PASS",
                   "path_snapshot_entries missing — skipping")
        return
    model = load_architecture_model(conn, args.project)
    if model is None:
        rec.record(_FORBIDDEN_EDGE, _FORBIDDEN_EDGE_DESC, "PASS",
                   "architecture_model not set for project — skipping")
        return
    allowed_edges, forbidden_edges = derive_edges(model)
    entries = iter_python_entries(conn, args.project)
    module_index = load_module_target_index(conn, args.project)
    parsed_entries = []
    context_ids = {target_id for target_id, _path, _mod, _deps in entries}
    findings: List[str] = []
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
            )
            if imp_target is not None:
                context_ids.add(imp_target)
    contexts = load_architecture_context(conn, context_ids)
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
            )
            if imp_target is None:
                continue
            imp_layer = contexts.get(imp_target, {}).get("layer")
            if imp_layer is None or imp_layer == source_layer:
                continue
            pair = (source_layer, imp_layer)
            if pair in forbidden_edges or pair not in allowed_edges:
                findings.append(
                    f"- {path}: {source_layer} → {imp_layer} via "
                    f"'{imp_module}' violates the architecture model. "
                    "Repair: route the dependency through an allowed "
                    "lower-layer module, OR add the edge to the layer's "
                    "may_depend_on list when the inversion is justified."
                )
    if not findings:
        rec.record(_FORBIDDEN_EDGE, _FORBIDDEN_EDGE_DESC, "PASS", "")
        return
    head = (
        f"- {len(findings)} forbidden / unsanctioned dependency edge(s) "
        "found in the latest HEAD snapshot."
    )
    rec.record(_FORBIDDEN_EDGE, _FORBIDDEN_EDGE_DESC, "WARN",
               format_findings(head, findings))


def _guarded_index(model) -> List[Tuple[str, str, str, List[str], List[str]]]:
    """Flatten ``cross_cutting_entrypoints[*].guarded_imports`` into a
    list of ``(ep_name, module, symbol, approved_modules,
    approved_module_prefixes)`` tuples used by the HC."""
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


def hc_architecture_cross_cutting_entrypoint(
    conn, args: DoctorArgs, rec: RecordCollector,
) -> None:
    if not _base._table_exists(conn, "path_snapshot_entries"):
        rec.record(_CROSS_CUTTING, _CROSS_CUTTING_DESC, "PASS",
                   "path_snapshot_entries missing — skipping")
        return
    model = load_architecture_model(conn, args.project)
    if model is None:
        rec.record(_CROSS_CUTTING, _CROSS_CUTTING_DESC, "PASS",
                   "architecture_model not set for project — skipping")
        return
    guarded = _guarded_index(model)
    if not guarded:
        rec.record(_CROSS_CUTTING, _CROSS_CUTTING_DESC, "PASS",
                   "no guarded_imports declared on cross-cutting entrypoints")
        return
    findings: List[str] = []
    for _tid, path, source_module, deps_text in iter_python_entries(
        conn, args.project,
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
                        f"- {path}: imports '{g_mod}.{g_name}' directly; "
                        f"entrypoint '{ep_name}' is reserved for "
                        f"{approved}. Repair: route the access through one "
                        "of the approved modules instead of importing the "
                        "underlying symbol."
                    )
    if not findings:
        rec.record(_CROSS_CUTTING, _CROSS_CUTTING_DESC, "PASS", "")
        return
    head = (
        f"- {len(findings)} cross-cutting-entrypoint violation(s) found "
        "in the latest HEAD snapshot."
    )
    rec.record(_CROSS_CUTTING, _CROSS_CUTTING_DESC, "WARN",
               format_findings(head, findings))


__all__ = [
    "hc_architecture_cross_cutting_entrypoint",
    "hc_architecture_forbidden_edge",
    "hc_architecture_unclassified_path",
]
