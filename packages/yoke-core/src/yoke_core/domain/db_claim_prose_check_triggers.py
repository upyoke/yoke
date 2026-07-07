r"""Trigger detection vocabulary for the prose-vs-claim gate.

Owns the regex patterns and the pure-detection helpers consumed by
:func:`yoke_core.domain.db_claim_prose_check.check` /
:func:`...check_item`:

* Compiled regex patterns and structural-trigger label set.
* :func:`detect_triggers` — pure regex detection over prose.
* :func:`_has_explicit_negative_db_claim` — sentence-level negative claim
  detector that clears vocabulary-only hits.
* :func:`_strip_code` — fenced-code / inline-code / tooling-line scrubber
  applied before detection.

Claim-state readers (``_claim_is_declared``, ``_claim_is_none``,
``_claim_reviewed_negative``) live in
:mod:`yoke_core.domain.db_claim_prose_check_state`.

Trigger phrase taxonomy:

* DDL verbs against table targets: ``ALTER TABLE``, ``CREATE TABLE``,
  ``DROP TABLE``, ``RENAME TABLE``, ``TRUNCATE TABLE``.
* DML against authoritative tables: ``INSERT INTO``, ``UPDATE``,
  ``DELETE FROM`` paired with a table name.
* Schema vocabulary: ``schema change``, ``schema migration``, ``column``
  in a mutation context, ``backfill``, ``bulk data``, ``add a column``,
  ``drop the column``.
* Governed-DB language: ``governed DB``, ``governed migration``,
  ``governed mutation``, ``authoritative DB``, ``authoritative database``,
  ``migration_audit``, ``migration module``.
* Identifier shape: ``migration: <slug>`` or ``migration_modules`` list
  references.

Match policy:

* All detection is case-insensitive.
* Phrases inside fenced code blocks (``\`\`\` ... \`\`\``) and inline
  code spans (``\`...\``) are ignored — those frequently quote shell
  commands or grep patterns that contain the trigger words without
  declaring DB mutation.
* Lines beginning with ``rg -``, ``grep -``, or ``python3 -m`` (after
  whitespace) are ignored — they are tooling references, not declarative
  prose.
"""

from __future__ import annotations

import re
from typing import Dict, List


# Compiled patterns — each carries an operator-facing label so the
# detector can report which rule fired.  Ordering is significant only for
# deduplication (longer / more specific rules listed first reduce noise).
_PROSE_PATTERNS: List[tuple] = [
    ("ALTER TABLE", re.compile(r"\bALTER\s+TABLE\b", re.IGNORECASE)),
    ("CREATE TABLE", re.compile(r"\bCREATE\s+TABLE\b", re.IGNORECASE)),
    ("DROP TABLE", re.compile(r"\bDROP\s+TABLE\b", re.IGNORECASE)),
    ("RENAME TABLE", re.compile(r"\bRENAME\s+TABLE\b", re.IGNORECASE)),
    ("TRUNCATE TABLE", re.compile(r"\bTRUNCATE\s+TABLE\b", re.IGNORECASE)),
    ("ALTER COLUMN", re.compile(r"\bALTER\s+COLUMN\b", re.IGNORECASE)),
    ("ADD COLUMN", re.compile(r"\bADD\s+COLUMN\b", re.IGNORECASE)),
    ("DROP COLUMN", re.compile(r"\bDROP\s+COLUMN\b", re.IGNORECASE)),
    (
        "add column",
        re.compile(
            r"\badd(?:s|ed|ing)?\s+(?:a\s+|the\s+)?(?:new\s+)?"
            r"(?:[A-Za-z_][A-Za-z0-9_]*\s+)?column\b",
            re.IGNORECASE,
        ),
    ),
    (
        "drop column",
        re.compile(
            r"\b(?:drop|remove)(?:s|d|ping|ing)?\s+(?:a\s+|the\s+)?"
            r"(?:[A-Za-z_][A-Za-z0-9_]*\s+)?column\b",
            re.IGNORECASE,
        ),
    ),
    (
        "rename column",
        re.compile(
            r"\brename(?:s|d|ing)?\s+(?:a\s+|the\s+)?"
            r"(?:[A-Za-z_][A-Za-z0-9_]*\s+)?column\b",
            re.IGNORECASE,
        ),
    ),
    (
        "INSERT INTO <table>",
        re.compile(r"\bINSERT\s+INTO\s+[A-Za-z_][A-Za-z0-9_]+", re.IGNORECASE),
    ),
    (
        "DELETE FROM <table>",
        re.compile(r"\bDELETE\s+FROM\s+[A-Za-z_][A-Za-z0-9_]+", re.IGNORECASE),
    ),
    (
        "UPDATE <table> SET",
        re.compile(
            r"\bUPDATE\s+[A-Za-z_][A-Za-z0-9_]+\s+SET\b", re.IGNORECASE
        ),
    ),
    ("schema migration", re.compile(r"\bschema\s+migration\b", re.IGNORECASE)),
    ("schema change", re.compile(r"\bschema\s+change[sd]?\b", re.IGNORECASE)),
    (
        "schema mutation",
        re.compile(r"\bschema\s+mutation[s]?\b", re.IGNORECASE),
    ),
    ("backfill", re.compile(r"\bback[\s-]?fill(?:ing|ed)?\b", re.IGNORECASE)),
    ("bulk data", re.compile(r"\bbulk\s+data\b", re.IGNORECASE)),
    ("governed DB", re.compile(r"\bgoverned\s+db\b", re.IGNORECASE)),
    (
        "governed migration",
        re.compile(r"\bgoverned\s+migration[s]?\b", re.IGNORECASE),
    ),
    (
        "governed mutation",
        re.compile(r"\bgoverned\s+mutation[s]?\b", re.IGNORECASE),
    ),
    (
        "authoritative DB",
        re.compile(r"\bauthoritative\s+(?:db|database)\b", re.IGNORECASE),
    ),
    ("migration_audit", re.compile(r"\bmigration_audit\b")),
    (
        "migration module",
        re.compile(r"\bmigration\s+module[s]?\b", re.IGNORECASE),
    ),
    ("migration_modules", re.compile(r"\bmigration_modules\b")),
    (
        "live DB mutation",
        re.compile(r"\blive\s+db\s+mutation[s]?\b", re.IGNORECASE),
    ),
    (
        "live DB schema",
        re.compile(r"\blive\s+db\s+schema\b", re.IGNORECASE),
    ),
    (
        "live DB apply",
        re.compile(r"\blive\s+db\s+apply\b", re.IGNORECASE),
    ),
    (
        "data migration",
        re.compile(r"\bdata\s+migration[s]?\b", re.IGNORECASE),
    ),
]

_STRUCTURAL_TRIGGER_LABELS = frozenset({
    "ALTER TABLE",
    "CREATE TABLE",
    "DROP TABLE",
    "RENAME TABLE",
    "TRUNCATE TABLE",
    "ALTER COLUMN",
    "ADD COLUMN",
    "DROP COLUMN",
    "add column",
    "drop column",
    "rename column",
    "INSERT INTO <table>",
    "DELETE FROM <table>",
    "UPDATE <table> SET",
})

_NEGATIVE_DB_CLAIM_PATTERNS: List[re.Pattern] = [
    re.compile(
        r"\b(?:this\s+(?:ticket|work)|the\s+ticket)\s+"
        r"(?:is\s+expected\s+to\s+be|is)\s+control-plane\s+code\s+only\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:do|does|must|should|will)\s+not\s+"
        r"(?:mutate|change|touch|modify|apply|execute|run|write|backfill)"
        r"[^.\n]{0,120}\b(?:live\s+)?(?:governed\s+)?"
        r"(?:db|database|schema|migration|mutation|bulk\s+data)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bno\s+(?:live\s+)?(?:db|database|schema|bulk\s+data|governed\s+db)"
        r"[^.\n]{0,80}\b(?:cleanup|backfill|mutation|migration|change|work)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bout\s+of\s+scope\b[^.\n]{0,120}\b"
        r"(?:live\s+db|db\s+schema|schema\s+migration|bulk\s+data|"
        r"backfill|governed\s+db)\b",
        re.IGNORECASE,
    ),
]


# Patterns within fenced code blocks (```...```) and inline code spans
# (`...`) get stripped before detection.
_FENCED_CODE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
# Whole-line strip — kill any line whose first non-whitespace token is a
# tooling invocation. The regex matches up to and including the trailing
# newline (or end of string) so the entire command line vanishes.
_TOOLING_LINE_RE = re.compile(
    r"^[ \t]*(?:rg|grep|python3?)\b[^\n]*(?:\n|\Z)",
    re.MULTILINE,
)


def _strip_code(prose: str) -> str:
    """Remove fenced code blocks, inline code spans, and tooling lines."""
    if not prose:
        return ""
    no_fenced = _FENCED_CODE_RE.sub(" ", prose)
    no_inline = _INLINE_CODE_RE.sub(" ", no_fenced)
    no_tools = _TOOLING_LINE_RE.sub(" ", no_inline)
    return no_tools


def detect_triggers(prose: str) -> List[tuple]:
    """Return a list of ``(label, snippet)`` for every fired pattern.

    Pure detection — no DB lookups.  Suitable for unit tests over raw
    prose strings.  Snippets are short context windows around the match
    so the operator-facing message can quote what triggered the gate.
    """
    if not prose:
        return []
    cleaned = _strip_code(prose)
    if not cleaned.strip():
        return []
    seen: Dict[str, str] = {}
    for label, pattern in _PROSE_PATTERNS:
        match = pattern.search(cleaned)
        if not match:
            continue
        if label in seen:
            continue
        snippet = _surrounding_window(cleaned, match.start(), match.end())
        seen[label] = snippet
    return [(label, snippet) for label, snippet in seen.items()]


def _has_explicit_negative_db_claim(prose: str) -> bool:
    """True when prose explicitly says the work does not mutate a governed DB."""
    cleaned = _strip_code(prose or "")
    if not cleaned.strip():
        return False
    return any(pattern.search(cleaned) for pattern in _NEGATIVE_DB_CLAIM_PATTERNS)


def _surrounding_window(text: str, start: int, end: int, *, radius: int = 40) -> str:
    """Return a ~80-character window around ``[start:end]`` for context."""
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    fragment = text[left:right].strip()
    fragment = re.sub(r"\s+", " ", fragment)
    if left > 0:
        fragment = "..." + fragment
    if right < len(text):
        fragment = fragment + "..."
    return fragment


__all__ = [
    "_STRUCTURAL_TRIGGER_LABELS",
    "_has_explicit_negative_db_claim",
    "_strip_code",
    "_surrounding_window",
    "detect_triggers",
]
