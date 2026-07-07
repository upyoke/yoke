"""Item-side architecture-fitness Doctor HCs.

Owns the two checks that read items / item-side state rather than the
project path snapshot:

* ``HC-architecture-impact-declaration`` — every item's
  ``architecture_impact`` value must be one of the closed enum; items
  that have advanced past ``refining-idea`` must not carry
  ``'uncertain'``.
* ``HC-architecture-scan-error`` — a ``path_snapshot_entries`` row no
  longer carries a JSON-parseable ``dependency_edges`` value, or it
  carries a stored Python import-scan failure sentinel. The HC catches
  scan failures without re-running the scanner; remediation is to fix
  the path and re-run ``path_snapshots`` for the affected project.

Path-based architecture HCs (unclassified-path, forbidden-edge,
cross-cutting-entrypoint) live in
:mod:`yoke_core.engines.doctor_hc_architecture`. All five are wired
through :mod:`yoke_core.engines.doctor_registry_architecture`.
"""

from __future__ import annotations

import json
from typing import List

import yoke_core.engines.doctor_report as _base
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector

from yoke_core.domain.architecture_impact import (
    ALLOWED_VALUES as _IMPACT_ALLOWED,
    IMPACT_UNCERTAIN,
)
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.engines.doctor_hc_architecture_helpers import format_findings


_IMPACT_DECL = "HC-architecture-impact-declaration"
_IMPACT_DECL_DESC = "Item architecture_impact value is invalid or unresolved"
_SCAN_ERROR = "HC-architecture-scan-error"
_SCAN_ERROR_DESC = "Stored dependency_edges value is invalid or scan failed"

# Item statuses that must NOT carry architecture_impact='uncertain'.
_NON_UNCERTAIN_STATUSES = (
    "refined-idea", "planning", "plan-drafted", "refining-plan", "planned",
    "implementing", "reviewing-implementation", "reviewed-implementation",
    "polishing-implementation", "implemented", "release", "done",
)


def hc_architecture_impact_declaration(
    conn, args: DoctorArgs, rec: RecordCollector,
) -> None:
    """Validate every item's architecture_impact value and flag any
    item past refining-idea that is still 'uncertain'."""
    if not _base._column_exists(conn, "items", "architecture_impact"):
        rec.record(_IMPACT_DECL, _IMPACT_DECL_DESC, "PASS",
                   "items.architecture_impact column missing — skipping")
        return
    rows = conn.execute(
        "SELECT id, status, architecture_impact FROM items "
        "WHERE architecture_impact IS NOT NULL",
    ).fetchall()
    findings: List[str] = []
    for row in rows:
        item_id, status, raw_value = row[0], row[1], row[2]
        value = (raw_value or "").strip().lower()
        if value not in _IMPACT_ALLOWED:
            findings.append(
                f"- YOK-{item_id}: architecture_impact='{raw_value}' is "
                f"not one of {sorted(_IMPACT_ALLOWED)}. Repair: rewrite "
                "via `db_router items update YOK-N architecture_impact "
                "--stdin` with a valid enum value."
            )
            continue
        if value == IMPACT_UNCERTAIN and status in _NON_UNCERTAIN_STATUSES:
            findings.append(
                f"- YOK-{item_id}: status='{status}' but "
                "architecture_impact='uncertain'. Refine should have "
                "resolved this to one of the three declared classes "
                "before advance to refined-idea."
            )
    if not findings:
        rec.record(_IMPACT_DECL, _IMPACT_DECL_DESC, "PASS", "")
        return
    head = f"- {len(findings)} architecture_impact issue(s) on items."
    rec.record(_IMPACT_DECL, _IMPACT_DECL_DESC, "WARN",
               format_findings(head, findings))


def hc_architecture_scan_error(
    conn, args: DoctorArgs, rec: RecordCollector,
) -> None:
    """Flag snapshot entries whose ``dependency_edges`` no longer
    parses as JSON. Detected without re-running the scanner."""
    if not _base._table_exists(conn, "path_snapshot_entries"):
        rec.record(_SCAN_ERROR, _SCAN_ERROR_DESC, "PASS",
                   "path_snapshot_entries missing — skipping")
        return
    project_id = resolve_project_id(conn, args.project)
    rows = conn.execute(
        "SELECT pse.target_id, pt.path_string, pse.dependency_edges "
        "FROM path_snapshot_entries pse "
        "JOIN path_snapshots ps ON ps.id = pse.snapshot_id "
        "JOIN path_targets pt ON pt.id = pse.target_id "
        "WHERE ps.project_id = %s AND pse.language = 'python' "
        "AND ps.id = ("
        "  SELECT id FROM path_snapshots "
        "  WHERE project_id = %s ORDER BY id DESC LIMIT 1"
        ")",
        (project_id, project_id),
    ).fetchall()
    findings: List[str] = []
    for target_id, path, deps_text in rows:
        try:
            edges = json.loads(deps_text or "[]")
        except (TypeError, ValueError) as exc:
            findings.append(
                f"- {path} (target {target_id}): dependency_edges no "
                f"longer parses as JSON ({type(exc).__name__}: {exc}). "
                "Repair: re-run `yoke project snapshot sync --project "
                "<project>` from the checkout to repopulate the row."
            )
            continue
        if not isinstance(edges, list):
            findings.append(
                f"- {path} (target {target_id}): dependency_edges parses "
                "but is not a JSON list. Repair: re-run "
                "`yoke project snapshot sync --project <project>` from the "
                "checkout to repopulate the row."
            )
            continue
        for edge in edges:
            if not isinstance(edge, dict) or not edge.get("scan_error"):
                continue
            findings.append(
                f"- {path} (target {target_id}): Python import scan failed "
                f"({edge['scan_error']}). Repair: fix the Python syntax "
                "or re-run `yoke project snapshot sync --project <project>` "
                "from the checkout after the file is parseable."
            )
    if not findings:
        rec.record(_SCAN_ERROR, _SCAN_ERROR_DESC, "PASS", "")
        return
    head = f"- {len(findings)} snapshot row(s) carry corrupt dependency_edges."
    rec.record(_SCAN_ERROR, _SCAN_ERROR_DESC, "WARN",
               format_findings(head, findings))


__all__ = [
    "hc_architecture_impact_declaration",
    "hc_architecture_scan_error",
]
