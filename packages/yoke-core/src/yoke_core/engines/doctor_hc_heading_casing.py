"""Doctor HC for canonical heading-casing across item content surfaces.

Yoke item bodies and operator sections use a standard set of headings —
``## Acceptance Criteria``, ``## File Budget``, ``## Simplify Pre-Check``,
``## Out of Scope``, ``## Non-Goals``, ``## Provenance``, ``## Path Claims``,
``## Progress Log``. Off-canon casing (``## Acceptance criteria`` etc.) silently
breaks case-sensitive section lookups via ``items get body --section "## ..."``
and the ``items.section.*`` function family — readers see no content instead
of seeing the wrong content, masking spec drift.

This HC scans the canonical narrative-content structured fields for each item
plus the ``item_sections.section_name`` rows, case-insensitively matches each
``## <heading>`` (and bare section_name) against the canonical set, and emits
WARN findings for any match whose casing diverges from the canonical form.
``body`` is intentionally excluded — it is a virtual rendered field built from
the structured fields and ``item_sections`` rows the HC already scans.

The HC's remediation prompt routes per surface to avoid the structured-field
``section_upsert`` duplicate-row trap: structured-field findings route to
``items.structured_field.replace`` (full rewrite preserves all other content);
``item_sections`` findings route to ``items.structured_field.section_upsert``
(no duplicate-row trap when the section IS the row).

For canonical headings owned by renderer-stripping (``## Path Claims`` is
produced by ``yoke_core.domain.path_claims_render`` and any operator-authored
copy is stripped from the rendered body by
``yoke_core.domain.render_body_section.strip_renderer_owned_section``), a
WARN finding describes stored content drift, not rendered-body drift.

Findings aggregate by canonical-form: one WARN per canonical heading enumerates
up to ten affected items with a ``... and N more`` truncation tail. Matches
the ``doctor_hc_path_claim_coordination`` aggregation shape.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Iterable, List, Tuple

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.items_constants import STRUCTURED_FIELDS

import yoke_core.engines.doctor_report as _base
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


_HC_NAME = "HC-heading-casing-canon"
_HC_DESC = "Canonical heading casing across item structured fields and sections"


# Canonical forms — operator-facing display strings. Lookup is case-insensitive
# via the lowercase index below. Add new canonical headings here only.
CANONICAL_HEADINGS: Tuple[str, ...] = (
    "Acceptance Criteria",
    "File Budget",
    "Simplify Pre-Check",
    "Out of Scope",
    "Non-Goals",
    "Provenance",
    "Path Claims",
    "Progress Log",
)


# Case-insensitive lookup index: {lower_form: canonical_form}.
_CANONICAL_BY_LOWER = {h.lower(): h for h in CANONICAL_HEADINGS}


# Narrative-content subset of STRUCTURED_FIELDS — operational fields contain
# JSON, not markdown headings, so scanning them adds noise without signal.
_NARRATIVE_STRUCTURED_FIELDS: Tuple[str, ...] = tuple(sorted(
    STRUCTURED_FIELDS - {
        "browser_qa_metadata",
        "db_mutation_profile",
        "db_compatibility_attestation",
        "architecture_impact",
    }
))


# Matches a level-2 markdown heading at the start of a line. Group 1 captures
# the heading text (everything after ``## `` to end of line).
_HEADING_RE = re.compile(r"^## (.+?)\s*$", re.MULTILINE)


def _scan_text_for_off_canon(text: str) -> Iterable[Tuple[str, str]]:
    """Yield ``(observed_heading, canonical_form)`` for every off-canon hit."""
    if not text:
        return
    for match in _HEADING_RE.finditer(text):
        observed = match.group(1).strip()
        canonical = _CANONICAL_BY_LOWER.get(observed.lower())
        if canonical and observed != canonical:
            yield observed, canonical


def _format_remediation(surface_kind: str) -> str:
    if surface_kind == "item_sections":
        return (
            "Fix via `items.structured_field.section_upsert` "
            "(the heading owns the section row — no duplicate-row trap)."
        )
    return (
        "Fix via `items.structured_field.replace` "
        "(full-field rewrite preserves all other content; avoids the "
        "section_upsert duplicate-row trap on structured-field-owned headings)."
    )


def _scan_structured_fields(conn) -> List[Tuple[str, str, int, str]]:
    """Return ``(surface, canonical, item_id, observed)`` rows for fields."""
    if not _base._table_exists(conn, "items"):
        return []
    select_clauses = ", ".join(_NARRATIVE_STRUCTURED_FIELDS)
    rows = query_rows(
        conn,
        f"SELECT id, {select_clauses} FROM items",
    )
    out: List[Tuple[str, str, int, str]] = []
    for row in rows:
        item_id = int(row["id"])
        for field in _NARRATIVE_STRUCTURED_FIELDS:
            text = row[field]
            if not text:
                continue
            for observed, canonical in _scan_text_for_off_canon(str(text)):
                out.append(
                    (f"structured_field:{field}", canonical, item_id, observed)
                )
    return out


def _scan_item_sections(conn) -> List[Tuple[str, str, int, str]]:
    """Return ``(surface, canonical, item_id, observed)`` rows for sections."""
    if not _base._table_exists(conn, "item_sections"):
        return []
    rows = query_rows(
        conn,
        "SELECT item_id, section_name FROM item_sections",
    )
    out: List[Tuple[str, str, int, str]] = []
    for row in rows:
        observed = str(row["section_name"] or "").strip()
        canonical = _CANONICAL_BY_LOWER.get(observed.lower())
        if canonical and observed != canonical:
            out.append(("item_sections", canonical, int(row["item_id"]), observed))
    return out


def hc_heading_casing_canon(
    conn, args: DoctorArgs, rec: RecordCollector
) -> None:
    """Flag case-insensitive matches against canonical headings whose casing differs.

    Scans every item's narrative structured fields (`spec`, `design_spec`,
    `technical_plan`, `worktree_plan`, `shepherd_log`, `shepherd_caveats`,
    `test_results`, `deploy_log`) for ``## <heading>`` lines, and every
    ``item_sections.section_name`` row. Findings aggregate by canonical-form;
    each finding names the canonical form, the offending text, and the surface.
    """
    findings = _scan_structured_fields(conn) + _scan_item_sections(conn)
    if not findings:
        rec.record(_HC_NAME, _HC_DESC, "PASS", "")
        return

    # Aggregate by canonical form: {canonical: [(item_id, observed, surface), ...]}
    by_canonical: dict[str, List[Tuple[int, str, str]]] = defaultdict(list)
    for surface, canonical, item_id, observed in findings:
        by_canonical[canonical].append((item_id, observed, surface))

    issues: List[str] = []
    for canonical in sorted(by_canonical):
        entries = by_canonical[canonical]
        # Stable order: by item_id, then by surface, then by observed.
        entries.sort(key=lambda e: (e[0], e[2], e[1]))
        # Group surface kinds present for the remediation hint.
        surface_kinds = {
            "item_sections" if s == "item_sections" else "structured_field"
            for _, _, s in entries
        }
        if surface_kinds == {"item_sections"}:
            remediation = _format_remediation("item_sections")
        elif surface_kinds == {"structured_field"}:
            remediation = _format_remediation("structured_field")
        else:
            remediation = (
                _format_remediation("structured_field") + " "
                + _format_remediation("item_sections")
            )
        issues.append(
            f"- `## {canonical}` — {len(entries)} off-canon occurrence(s). "
            f"{remediation}"
        )
        for item_id, observed, surface in entries[:10]:
            issues.append(
                f"  - YOK-{item_id} [{surface}]: `## {observed}` "
                f"-> `## {canonical}`"
            )
        if len(entries) > 10:
            issues.append(f"  - ... and {len(entries) - 10} more")

    rec.record(_HC_NAME, _HC_DESC, "WARN", "\n".join(issues))


__all__ = [
    "CANONICAL_HEADINGS",
    "hc_heading_casing_canon",
]
