"""HC-tier-schema-bleed — Tier 0/2/4/5 surfaces must not restate Tier 1.

Tier 1 (the auto-loaded ``schema_api_context`` packet) is the single
authoritative source for structural truth — table column names, JSON
nested-field shapes, CLI surfaces, enum values. Tiers 0/2/4/5 should
cite *toward* Tier 1 rather than restate its facts; restated facts
drift independently from the canonical packet and bite agents at
conduct time (the motivation).

This HC scans the scannable tiers (via :func:`iter_tier_paths`) and
flags two confabulation-prone patterns:

**Class A — direct ``<table>.<column>`` bleed.** Lines outside fenced
code blocks that name a real ``CANONICAL_TABLES`` table-and-column pair
without using a sanctioned cross-reference prefix. A confabulated
column on a real table (e.g. ``epic_tasks.depends_on``) is also
flagged — the table reference indicates schema teaching is happening
on a non-Tier-1 surface, and the column doesn't exist anyway.

**Class B — JSON-nested-field-as-top-level access.** Lines containing
``items get YOK-N <field>`` or ``items get <bare-int> <field>`` where
``<field>`` is a nested field defined inside a JSON column per
:data:`JSON_NESTED_SCHEMAS`. The remediation message names the parent
JSON column and :data:`ACCESS_PATTERN_NOTE`; Class B applies inside
fenced code blocks too because a fenced example with the wrong shape
is still wrong teaching.

Severity is WARN in v0 — the bleed corpus is non-empty and this HC
exists to put downward pressure on it without blocking baseline runs.
Findings are truncated to a fixed budget so one bleed-heavy file does
not drown the doctor report.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from yoke_core.domain.schema_api_context_json_schemas import (
    ACCESS_PATTERN_NOTE,
    JSON_NESTED_SCHEMAS,
)
from yoke_core.domain.schema_api_context_tables import CANONICAL_TABLES
from yoke_core.engines.doctor_registry_tier_discipline import (
    TIER_GLOBS,
    TIER_6_ARCHIVE_PREFIXES,
    is_cross_reference_line,
    iter_tier_paths,
)
from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
    _resolve_repo_root,
)


HC_SLUG = "HC-tier-schema-bleed"
HC_LABEL = (
    "Tier 0/2/4/5 surface references schema column outside "
    "cross-reference allow-list"
)
_MAX_FINDINGS = 40


# ---------------------------------------------------------------------------
# Lookup tables (built once at module import; pure functions of canonical
# upstream constants — they grow automatically as those constants grow).
# ---------------------------------------------------------------------------

# table_name -> set of real column names.
_TABLE_COLUMNS: Dict[str, set] = {
    table: {col for col, _sqltype in meta.get("columns", [])}
    for table, meta in CANONICAL_TABLES.items()
}

# (table, json_col) -> (set-of-nested-field-names, ...) — exact metadata
# tuple used by Class B for both the existence check and the remediation
# message. We carry the parent json column verbatim so the remediation
# message names it without re-deriving from the field.
_JSON_FIELD_INDEX: Dict[str, List[Tuple[str, str]]] = {}
for (_table, _json_col), _meta in JSON_NESTED_SCHEMAS.items():
    for _field in _meta["fields"]:
        _field_name = _field[0]
        # Skip "(JSON array ...)" placeholder rows whose field name is a
        # parenthetical description rather than a real key (e.g.
        # epic_tasks.dependencies, qa_requirements.capability_requirements).
        if _field_name.startswith("("):
            continue
        _JSON_FIELD_INDEX.setdefault(_field_name, []).append((_table, _json_col))


# Class A pattern: word-boundary <table>.<column>. We extract every
# ``identifier.identifier`` pair on the line, then validate against the
# canonical-tables index. This keeps the regex agnostic of which tables
# exist — growth in CANONICAL_TABLES is picked up automatically.
_TABLE_COL_RE = re.compile(r"\b([a-z_][a-z0-9_]*)\.([a-z_][a-z0-9_]*)\b")

# Class B pattern: ``items get YOK-N <field>`` or ``items get <bare-int>
# <field>``. The trailing field token is captured for index lookup.
_ITEMS_GET_RE = re.compile(
    r"\bitems\s+get\s+"
    r"(?:YOK-\d+|\d+)"
    r"\s+([a-z_][a-z0-9_]*)\b"
)


def _scan_file(rel_path: str, text: str) -> List[str]:
    """Return formatted bleed findings for one tier-scoped file.

    Class A respects fenced code blocks (triple-backtick toggle); Class B
    runs on every line because a fenced example with a nested-field shape
    is still bad teaching.
    """

    findings: List[str] = []
    in_fence = False
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip("\n")
        stripped = line.lstrip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue

        # --- Class B: JSON nested field accessed as top-level column. ---
        # Applies inside fenced code blocks too.
        for match in _ITEMS_GET_RE.finditer(line):
            field = match.group(1)
            parents = _JSON_FIELD_INDEX.get(field)
            if not parents:
                continue
            for table, json_col in parents:
                findings.append(
                    f"- {rel_path}:{lineno}: `items get ... {field}` accesses "
                    f"a nested key of `{table}.{json_col}` as a top-level "
                    f"column — {ACCESS_PATTERN_NOTE}"
                )

        # --- Class A: <table>.<column> references outside fences. ---
        if in_fence:
            continue
        if is_cross_reference_line(line):
            continue
        for match in _TABLE_COL_RE.finditer(line):
            table = match.group(1)
            column = match.group(2)
            cols = _TABLE_COLUMNS.get(table)
            if cols is None:
                continue
            if column in cols:
                findings.append(
                    f"- {rel_path}:{lineno}: `{table}.{column}` restates "
                    "Tier 1 structural truth outside the cross-reference "
                    "allow-list"
                )
            else:
                findings.append(
                    f"- {rel_path}:{lineno}: `{table}.{column}` references "
                    f"a non-existent column on real table `{table}` "
                    "(confabulation)"
                )
    return findings


def _scan_all(repo_root: Path, tiers: Iterable[int] = (0, 2, 4, 5)) -> List[str]:
    findings: List[str] = []
    for _tier, abs_path in iter_tier_paths(repo_root, tiers=tiers):
        rel = abs_path.relative_to(repo_root).as_posix()
        # Defense-in-depth archive skip (iter_tier_paths already skips by
        # default for the tiers we pass, but archive prefixes elsewhere
        # remain explicitly exempt).
        if any(rel.startswith(prefix) for prefix in TIER_6_ARCHIVE_PREFIXES):
            continue
        try:
            text = abs_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        findings.extend(_scan_file(rel, text))
    return findings


def _format_detail(findings: List[str]) -> str:
    if len(findings) <= _MAX_FINDINGS:
        return "\n".join(findings)
    truncated = findings[:_MAX_FINDINGS]
    extra = len(findings) - _MAX_FINDINGS
    truncated.append(f"… {extra} more references")
    return "\n".join(truncated)


def hc_tier_schema_bleed(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-tier-schema-bleed: tier-discipline structural-truth bleed scan."""

    repo_root = _resolve_repo_root()
    if not repo_root:
        rec.record(HC_SLUG, HC_LABEL, "PASS", "repo root not resolvable (skip)")
        return

    findings = _scan_all(Path(repo_root))
    if findings:
        rec.record(HC_SLUG, HC_LABEL, "WARN", _format_detail(findings))
    else:
        rec.record(HC_SLUG, HC_LABEL, "PASS", "")


__all__ = ["hc_tier_schema_bleed", "HC_SLUG", "HC_LABEL", "TIER_GLOBS"]
