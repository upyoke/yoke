"""Mechanical compatibility scanner for governed DB mutations.

Per §6.1b of the governed-DB-mutation contract (governed DB-mutation contract): runs against
declared DDL or affected-surface DDL during the ``idea → refining-idea``
joint gate (§7.1).  Any banned-pattern hit escalates a declared
``pre_merge_safe`` compatibility class to ``pre_merge_breaking``.

Dispatch is keyed by the referenced migration model's
``authoritative_db.kind``; the destructive DDL rules apply to both
``sqlite_file`` and ``postgres`` authority.

Scanner rules are the **single source of truth** — not duplicated on the
capability, in docs, or on the flow.  Callers never enumerate banned
patterns inline.

Module surface::

    hits = scan(ddl_text, authoritative_db_kind="sqlite_file")
    if hits:
        # declared pre_merge_safe must escalate; operator decomposes,
        # defers, or routes through the exception pathway.
        for hit in hits:
            print(hit.pattern_id, hit.reason)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Iterable, List, Mapping, Tuple


@dataclass(frozen=True)
class ScannerHit:
    """One banned-pattern match.

    ``pattern_id``: stable identifier used by tests, audit rows, and
    escalation records.
    ``snippet``: the source fragment that matched (trimmed, single-line).
    ``reason``: human-readable explanation (operator-facing).
    ``line_number``: 1-indexed line in the scanned DDL.
    """

    pattern_id: str
    snippet: str
    reason: str
    line_number: int


# ---------------------------------------------------------------------------
# SQLite ruleset (MVP)
# ---------------------------------------------------------------------------
#
# Each entry:
#   id      — stable slug; test fixtures and escalation audit rows key off this
#   regex   — compiled case-insensitive pattern
#   reason  — operator-facing reason text when the pattern hits
#
# Regex guidance:
#   - Ignore leading whitespace and statement-level indentation.
#   - Use ``re.IGNORECASE`` so casing variation in author-written DDL
#     does not slip past the scanner.
#   - Match within a single statement; callers strip comments before
#     dispatching (see :func:`_strip_sql_comments`).


_DROP_TABLE_RE = re.compile(
    r"\bDROP\s+TABLE\b(?:\s+IF\s+EXISTS)?", re.IGNORECASE,
)
_DROP_INDEX_RE = re.compile(
    r"\bDROP\s+INDEX\b", re.IGNORECASE,
)
_DROP_COLUMN_RE = re.compile(
    r"\bALTER\s+TABLE\s+\S+\s+DROP\s+(?:COLUMN\s+)?\w+", re.IGNORECASE,
)
_RENAME_COLUMN_RE = re.compile(
    r"\bALTER\s+TABLE\s+\S+\s+RENAME\s+COLUMN\b", re.IGNORECASE,
)
_RENAME_TABLE_RE = re.compile(
    r"\bALTER\s+TABLE\s+\S+\s+RENAME\s+TO\b", re.IGNORECASE,
)
# ADD COLUMN ... NOT NULL without a DEFAULT in the same column spec.
# Explicit non-capturing group avoids matching statements whose DEFAULT
# clause is present even if ordered unusually.
_ADD_COLUMN_NOT_NULL_NO_DEFAULT_RE = re.compile(
    r"\bALTER\s+TABLE\s+\S+\s+ADD\s+(?:COLUMN\s+)?"
    r"\w+(?:\s+[A-Z][A-Z0-9_]*)?"        # optional bare type token
    r"(?=[^;]*\bNOT\s+NULL\b)"            # must declare NOT NULL
    r"(?![^;]*\bDEFAULT\b)"               # but must NOT declare DEFAULT
    r"[^;]*?\bNOT\s+NULL\b[^;]*;?",
    re.IGNORECASE,
)
_CREATE_UNIQUE_INDEX_RE = re.compile(
    r"\bCREATE\s+UNIQUE\s+INDEX\b", re.IGNORECASE,
)
# DELETE without a WHERE clause — treated as a bulk mutation unless
# author invariants explicitly accept a truncation.  Matches
# ``DELETE FROM t;`` and ``DELETE FROM t`` end-of-statement.
_DELETE_NO_WHERE_RE = re.compile(
    r"\bDELETE\s+FROM\s+\S+\s*(?:;|$)", re.IGNORECASE,
)


def _dispatch_sqlite(statement: str) -> List[Tuple[str, str]]:
    """Return a list of ``(pattern_id, reason)`` hits for one SQL statement."""
    hits: List[Tuple[str, str]] = []

    if _DROP_TABLE_RE.search(statement):
        hits.append((
            "sqlite.drop_table",
            "DROP TABLE on a pre-existing surface is pre_merge_breaking — "
            "readers on main still expect the table.",
        ))
    if _DROP_COLUMN_RE.search(statement):
        hits.append((
            "sqlite.drop_column",
            "ALTER TABLE ... DROP COLUMN is pre_merge_breaking — readers on "
            "main still select the column.",
        ))
    if _DROP_INDEX_RE.search(statement):
        hits.append((
            "sqlite.drop_index",
            "DROP INDEX is pre_merge_breaking when readers rely on the "
            "index for correctness or performance SLOs.",
        ))
    if _RENAME_COLUMN_RE.search(statement):
        hits.append((
            "sqlite.rename_column",
            "ALTER TABLE ... RENAME COLUMN is pre_merge_breaking — readers "
            "on main still use the old name. Decompose into expand "
            "(add new column + dual-write) → contract (drop old column).",
        ))
    if _RENAME_TABLE_RE.search(statement):
        hits.append((
            "sqlite.rename_table",
            "ALTER TABLE ... RENAME TO is pre_merge_breaking — readers on "
            "main still use the old table name.",
        ))
    if _ADD_COLUMN_NOT_NULL_NO_DEFAULT_RE.search(statement):
        hits.append((
            "sqlite.add_column_not_null_no_default",
            "ADD COLUMN with NOT NULL and no DEFAULT is pre_merge_breaking — "
            "existing rows cannot satisfy the constraint.",
        ))
    if _CREATE_UNIQUE_INDEX_RE.search(statement):
        hits.append((
            "sqlite.create_unique_index",
            "CREATE UNIQUE INDEX is pre_merge_breaking when pre-existing "
            "rows may not satisfy uniqueness. Confirm by author invariants "
            "or decompose through a normalization pass first.",
        ))
    if _DELETE_NO_WHERE_RE.search(statement):
        hits.append((
            "sqlite.delete_no_where",
            "DELETE FROM <table> without a WHERE clause truncates the table "
            "and is pre_merge_breaking unless row-count preservation is "
            "explicitly waived.",
        ))
    return hits


def _dispatch_postgres(statement: str) -> List[Tuple[str, str]]:
    return [
        (pattern_id.replace("sqlite.", "postgres.", 1), reason)
        for pattern_id, reason in _dispatch_sqlite(statement)
    ]


# Registry keyed by authoritative_db.kind.
_DISPATCHERS: Mapping[str, Callable[[str], List[Tuple[str, str]]]] = {
    "sqlite_file": _dispatch_sqlite,
    "postgres": _dispatch_postgres,
}


def supported_kinds() -> Iterable[str]:
    return tuple(_DISPATCHERS.keys())


class UnsupportedDbKindError(ValueError):
    """Raised when no dispatcher exists for the requested DB kind."""


def _strip_sql_comments(sql: str) -> str:
    """Strip ``--`` line comments and ``/* ... */`` block comments.

    Preserves line numbering for ``--`` comments by replacing them with
    empty strings up to the newline; block comments collapse to a single
    space to keep statement boundaries intact without polluting line
    counts when the block spans multiple lines.
    """
    sql = re.sub(r"--[^\n]*", "", sql)
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    return sql


def _split_statements(sql: str) -> List[Tuple[int, str]]:
    """Split DDL text into ``(line_number, statement)`` pairs.

    Naive splitter keyed on semicolons — good enough for the banned-pattern
    regexes which are statement-local.  Ignores empty and whitespace-only
    statements.  Line numbers are 1-indexed and refer to the first
    non-whitespace character of each statement.
    """
    out: List[Tuple[int, str]] = []
    line = 1
    buf: List[str] = []
    buf_start = 1
    for ch in sql:
        # Consume leading whitespace outside any statement so the
        # statement's line number tracks its first real character.
        if not buf and ch in " \t\r\n":
            if ch == "\n":
                line += 1
            buf_start = line
            continue
        buf.append(ch)
        if ch == ";":
            statement = "".join(buf).strip()
            if statement and statement != ";":
                out.append((buf_start, statement))
            buf = []
            buf_start = line
        elif ch == "\n":
            line += 1
    tail = "".join(buf).strip()
    if tail:
        out.append((buf_start, tail))
    return out


def scan(
    ddl_text: str, *, authoritative_db_kind: str
) -> List[ScannerHit]:
    """Scan *ddl_text* for banned patterns under *authoritative_db_kind*.

    Returns a list of :class:`ScannerHit` — one per matched pattern per
    statement.  An empty list means no banned patterns were detected;
    the caller honors the declared compatibility class.

    Raises :class:`UnsupportedDbKindError` when no dispatcher exists.
    """
    dispatcher = _DISPATCHERS.get(authoritative_db_kind)
    if dispatcher is None:
        raise UnsupportedDbKindError(
            f"no scanner ruleset for authoritative_db.kind '{authoritative_db_kind}'. "
            f"Supported kinds: {sorted(supported_kinds())}"
        )

    cleaned = _strip_sql_comments(ddl_text or "")
    hits: List[ScannerHit] = []
    for line_no, statement in _split_statements(cleaned):
        snippet = " ".join(statement.split())
        if len(snippet) > 160:
            snippet = snippet[:157] + "..."
        for pattern_id, reason in dispatcher(statement):
            hits.append(
                ScannerHit(
                    pattern_id=pattern_id,
                    snippet=snippet,
                    reason=reason,
                    line_number=line_no,
                )
            )
    return hits


def has_banned_pattern(ddl_text: str, *, authoritative_db_kind: str) -> bool:
    """Convenience boolean over :func:`scan`."""
    return bool(scan(ddl_text, authoritative_db_kind=authoritative_db_kind))


__all__ = [
    "ScannerHit",
    "UnsupportedDbKindError",
    "has_banned_pattern",
    "scan",
    "supported_kinds",
]
