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
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from yoke_core.domain.schema_api_context_json_schemas import (
    ACCESS_PATTERN_NOTE,
    JSON_NESTED_SCHEMAS,
)
from yoke_core.domain.schema_api_context_tables import CANONICAL_TABLES
from yoke_core.domain.items_constants import LARGE_TEXT_FIELDS
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


# Class A pattern: a complete dotted identifier. Reading the complete token,
# rather than only its first two components, lets the scanner distinguish
# registered function ids such as ``items.structured_field.replace`` from
# schema references such as ``items.worktree_path``.
_DOTTED_IDENTIFIER_RE = re.compile(
    r"\b[a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)+\b"
)
_NON_SCHEMA_DOTTED_SUFFIXES = frozenset({".json", ".md", ".py", ".toml"})
# Item structured fields are agent-facing read/write projections, and ``body``
# is rendered virtually. Their dotted names describe the item API rather than
# teaching raw table shape, even when a structured field has physical storage.
_ITEM_PUBLIC_FIELD_REFERENCES = LARGE_TEXT_FIELDS

# Class B pattern: ``items get YOK-N <field>`` or ``items get <bare-int>
# <field>``. The trailing field token is captured for index lookup.
_ITEMS_GET_RE = re.compile(
    r"\bitems\s+get\s+"
    r"(?:YOK-\d+|\d+)"
    r"\s+([a-z_][a-z0-9_]*)\b"
)


@lru_cache(maxsize=1)
def _registered_function_tokens() -> frozenset[str]:
    """Return registered function ids and their multi-part family prefixes."""

    from yoke_core.domain.yoke_function_dispatch import _ensure_handlers_registered
    from yoke_core.domain.yoke_function_registry import list_entries

    _ensure_handlers_registered()
    tokens: set[str] = set()
    for entry in list_entries():
        parts = entry.function_id.split(".")
        for end in range(2, len(parts) + 1):
            token_parts = parts[:end]
            if (
                end == 2
                and token_parts[0] in _TABLE_COLUMNS
                and token_parts[1] in _TABLE_COLUMNS[token_parts[0]]
            ):
                continue
            tokens.add(".".join(token_parts))
    return frozenset(tokens)


def extract_schema_references(text: str) -> List[Tuple[str, str]]:
    """Return distinct table-column pairs, excluding other dotted syntax."""

    pairs: List[Tuple[str, str]] = []
    seen: set[Tuple[str, str]] = set()
    function_tokens = _registered_function_tokens()
    for match in _DOTTED_IDENTIFIER_RE.finditer(text):
        token = match.group(0)
        if token.endswith(tuple(_NON_SCHEMA_DOTTED_SUFFIXES)):
            continue
        table, column, *_rest = token.split(".")
        if table not in CANONICAL_TABLES:
            continue
        if table == "items" and column in _ITEM_PUBLIC_FIELD_REFERENCES:
            continue
        # A registered function id can share its leading components with a
        # physical table-column pair (for example ``deployment_flows.stages``
        # and ``projects.github_sync_mode.repair``). Physical schema truth
        # wins that collision: suppress function syntax only after proving
        # its first two components are not a real column.
        if column not in _TABLE_COLUMNS.get(table, set()) and token in function_tokens:
            continue
        pair = (table, column)
        if pair in seen:
            continue
        seen.add(pair)
        pairs.append(pair)
    return pairs


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
        for table, column in extract_schema_references(line):
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


__all__ = [
    "hc_tier_schema_bleed",
    "extract_schema_references",
    "HC_SLUG",
    "HC_LABEL",
    "TIER_GLOBS",
]

# Slug and display name are the ones this check has always reported under.
from yoke_project_checks._declare import (  # noqa: E402
    self_project_checks,
)

PROJECT_HEALTH_CHECKS = self_project_checks(
    ('tier-schema-bleed', 'Tier 0/2/4/5 surfaces restate Tier 1 schema facts', hc_tier_schema_bleed),
)
