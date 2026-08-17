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
  marked as restricted.

The findings themselves come from the shared computers in
:mod:`yoke_core.domain.architecture_health` — the same definition the
board section and the dashboard read surface consume — so a Doctor
warning and a dashboard violation can never disagree. This module owns
only guard rails, message shaping, and severity.

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

from typing import List

import yoke_core.engines.doctor_report as _base
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector

from yoke_core.domain.architecture_health import (
    cross_cutting_violations,
    forbidden_edge_violations,
    unclassified_paths,
)
from yoke_core.engines.doctor_hc_architecture_helpers import (
    format_findings,
    load_architecture_model,
)


_UNCLASSIFIED = "HC-architecture-unclassified-path"
_UNCLASSIFIED_DESC = "Observed path has no inherited architecture domain or layer"
_FORBIDDEN_EDGE = "HC-architecture-forbidden-edge"
_FORBIDDEN_EDGE_DESC = "Recorded dependency edge violates the architecture model"
_CROSS_CUTTING = "HC-architecture-cross-cutting-entrypoint"
_CROSS_CUTTING_DESC = "Non-approved module imports a guarded cross-cutting symbol"


def _model_or_skip(conn, args, rec, hc_name: str, hc_desc: str):
    if not _base._table_exists(conn, "path_snapshot_entries"):
        rec.record(hc_name, hc_desc, "PASS",
                   "path_snapshot_entries missing — skipping")
        return None
    model = load_architecture_model(conn, args.project)
    if model is None:
        rec.record(hc_name, hc_desc, "PASS",
                   "architecture_model not set for project — skipping")
        return None
    return model


def hc_architecture_unclassified_path(
    conn, args: DoctorArgs, rec: RecordCollector,
) -> None:
    model = _model_or_skip(conn, args, rec, _UNCLASSIFIED, _UNCLASSIFIED_DESC)
    if model is None:
        return
    findings: List[str] = [
        f"- {path} (target {target_id}) has no inherited "
        "architecture_layer / architecture_domain. Set one of "
        "{architecture_layer, architecture_domain} via "
        "path_context_values or mark the path with an exemption family."
        for target_id, path in unclassified_paths(
            conn, args.project, model=model,
        )
    ]
    if not findings:
        rec.record(_UNCLASSIFIED, _UNCLASSIFIED_DESC, "PASS", "")
        return
    head = (
        f"- {len(findings)} python path(s) lack architecture classification. "
        "Each must inherit an architecture_layer or architecture_domain, "
        "OR carry an exemption family (architecture_generated, "
        "architecture_fixture, architecture_archive, "
        "architecture_test_surface, architecture_pack_source)."
    )
    rec.record(_UNCLASSIFIED, _UNCLASSIFIED_DESC, "WARN",
               format_findings(head, findings))


def hc_architecture_forbidden_edge(
    conn, args: DoctorArgs, rec: RecordCollector,
) -> None:
    model = _model_or_skip(
        conn, args, rec, _FORBIDDEN_EDGE, _FORBIDDEN_EDGE_DESC,
    )
    if model is None:
        return
    findings: List[str] = [
        f"- {path}: {source_layer} → {imp_layer} via "
        f"'{imp_module}' violates the architecture model. "
        "Repair: route the dependency through an allowed "
        "lower-layer module, OR add the edge to the layer's "
        "may_depend_on list when the inversion is justified."
        for path, source_layer, imp_layer, imp_module
        in forbidden_edge_violations(conn, args.project, model=model)
    ]
    if not findings:
        rec.record(_FORBIDDEN_EDGE, _FORBIDDEN_EDGE_DESC, "PASS", "")
        return
    head = (
        f"- {len(findings)} forbidden / unsanctioned dependency edge(s) "
        "found in the latest HEAD snapshot."
    )
    rec.record(_FORBIDDEN_EDGE, _FORBIDDEN_EDGE_DESC, "WARN",
               format_findings(head, findings))


def hc_architecture_cross_cutting_entrypoint(
    conn, args: DoctorArgs, rec: RecordCollector,
) -> None:
    model = _model_or_skip(
        conn, args, rec, _CROSS_CUTTING, _CROSS_CUTTING_DESC,
    )
    if model is None:
        return
    entrypoints = model.get("cross_cutting_entrypoints") or {}
    if not any(
        isinstance(ep, dict) and ep.get("guarded_imports")
        for ep in entrypoints.values()
    ):
        rec.record(_CROSS_CUTTING, _CROSS_CUTTING_DESC, "PASS",
                   "no guarded_imports declared on cross-cutting entrypoints")
        return
    findings: List[str] = [
        f"- {path}: imports '{symbol}' directly; "
        f"entrypoint '{ep_name}' is reserved for "
        f"{approved}. Repair: route the access through one "
        "of the approved modules instead of importing the "
        "underlying symbol."
        for path, ep_name, symbol, approved
        in cross_cutting_violations(conn, args.project, model=model)
    ]
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
