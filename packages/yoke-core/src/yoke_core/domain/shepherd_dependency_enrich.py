"""Dependency enrichment command for shepherd blocker rows."""
from __future__ import annotations

import sys

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_rows


def cmd_dependency_enrich(conn) -> str:
    rows = query_rows(
        conn,
        "SELECT d.id, d.dependent_item, d.blocking_item, d.gate_point, "
        "d.satisfaction, d.source, d.rationale, d.evidence_json, "
        "COALESCE(bi.title, ''), COALESCE(di.title, '') "
        "FROM item_dependencies d "
        "LEFT JOIN items bi ON bi.id = CAST(REPLACE(d.blocking_item, 'YOK-', '') AS INTEGER) "
        "LEFT JOIN items di ON di.id = CAST(REPLACE(d.dependent_item, 'YOK-', '') AS INTEGER) "
        "WHERE d.rationale IN ('', 'Operator-declared dependency', "
        "'Operator-declared activation dependency', "
        "'Operator-declared integration dependency', "
        "'Operator-declared closure dependency', "
        "'Migrated from legacy depends_on field', "
        "'Created during shepherd pipeline', "
        "'Created during conduct execution') "
        "OR d.evidence_json IN ('', '{}') "
        "ORDER BY d.id",
    )
    if not rows:
        print("No dependency rows need enrichment.", file=sys.stderr)
        return "OK"

    enriched = 0
    for row in rows:
        (
            row_id,
            dependent,
            blocking,
            gate_point,
            satisfaction,
            source,
            rationale,
            evidence_json,
            blocking_title,
            _dependent_title,
        ) = tuple(row)
        new_rationale = _enriched_rationale(
            dependent,
            blocking,
            gate_point,
            satisfaction,
            source,
            rationale,
            blocking_title,
        )
        new_evidence = _enriched_evidence(source, evidence_json)
        if new_rationale == rationale and new_evidence == evidence_json:
            continue
        p = "%s" if db_backend.connection_is_postgres(conn) else "?"
        conn.execute(
            f"UPDATE item_dependencies SET rationale={p}, evidence_json={p} WHERE id={p}",
            (new_rationale, new_evidence, row_id),
        )
        print(f"  ENRICHED|id={row_id}|{dependent}->{blocking}|{gate_point}", file=sys.stderr)
        enriched += 1

    conn.commit()
    print("Enrichment complete.", file=sys.stderr)
    return "OK"


def _enriched_rationale(
    dependent: str,
    blocking: str,
    gate_point: str,
    satisfaction: str,
    source: str,
    rationale: str,
    blocking_title: str,
) -> str:
    generic_rationales = {
        "",
        "Operator-declared dependency",
        "Operator-declared activation dependency",
        "Operator-declared integration dependency",
        "Operator-declared closure dependency",
    }
    if rationale in generic_rationales:
        if blocking_title:
            return (
                f"{dependent} blocked at {gate_point} gate until {blocking} "
                f"({blocking_title}) satisfies {satisfaction}"
            )
        return f"{dependent} blocked at {gate_point} gate until {blocking} satisfies {satisfaction}"
    if rationale == "Migrated from legacy depends_on field" and blocking_title:
        return f"Legacy activation dependency: {dependent} waits for {blocking} ({blocking_title})"
    if rationale == "Created during shepherd pipeline" and blocking_title:
        return f"Shepherd-declared: {dependent} requires {blocking} ({blocking_title}) at {gate_point}"
    if rationale == "Created during conduct execution" and blocking_title:
        return f"Conduct-declared: {dependent} requires {blocking} ({blocking_title}) at {gate_point}"
    return rationale


def _enriched_evidence(source: str, evidence_json: str) -> str:
    if evidence_json not in ("", "{}"):
        return evidence_json
    evidence_map = {
        "operator": '{"created_by":"operator"}',
        "shepherd": '{"created_by":"shepherd"}',
        "conduct": '{"created_by":"conduct"}',
        "feed": '{"created_by":"feed"}',
        "migration": '{"migrated_from":"depends_on"}',
    }
    return evidence_map.get(source, f'{{"created_by":"{source}"}}')
