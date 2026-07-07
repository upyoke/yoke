"""Scanner core for the historical ``YOK-N`` cruft lint.

Owns the scan scope, exemption rules, ticket-status lookup, allowed-context
predicate, and the public :func:`scan` entry point. The companion
:mod:`yoke_core.domain.lint_yok_n_cruft` module wraps this with the CLI
formatter and re-exports the public surface so callers can keep importing
``yoke_core.domain.lint_yok_n_cruft.scan``.

See :mod:`yoke_core.domain.lint_yok_n_cruft` for the policy doctrine and
operator-facing usage.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional, Sequence

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import connect

# ---------------------------------------------------------------------------
# Scan scope
# ---------------------------------------------------------------------------

# Markdown prose plus Python source; ``.py`` carries historical ticket
# provenance in comments/docstrings that should be swept like ``.md`` cruft.
# Allowed-context rules below exempt ``test_sun_N_*`` function names and
# quoted ticket literals (for example, ``"YOK-" + str(item_id)``) so test data and doc examples
# aren't flagged.
_SCAN_EXTS: tuple[str, ...] = (".md", ".py")

# Default scope: doctrine root files, operator-facing docs, canonical skill
# bodies, and runtime code/tests/agent prompts. Out-of-default surfaces
# (.yoke/strategy/, templates/, projects/, `.claude/` compat symlinks) are either
# knowledge-layer inventory, templates with separate hygiene, or mirrors.
_DEFAULT_SCAN_DIRS: tuple[str, ...] = (
    "docs",
    ".agents/skills/yoke",
    "runtime",
)

# Top-level files outside scanned directories. ``CLAUDE.md`` is a compat
# symlink to ``AGENTS.md``; scanning both would double-count.
_DEFAULT_SCAN_ROOT_FILES: tuple[str, ...] = (
    "AGENTS.md",
    "README.md",
)

# Path segments excluded by policy: ``docs/archive/`` (the durable stable-slug
# home for architectural-why decision records); knowledge-layer inventory
# surfaces (``ouroboros/``, ``wrapup_reports/``, ``.yoke/strategy/``) that carry
# ticket IDs as data; ``.claude/`` compat symlink that would double-count.
_EXEMPT_PATH_SEGMENTS: tuple[str, ...] = (
    "archive",
    "ouroboros",
    "wrapup_reports",
    "strategy",
    ".claude",
    "node_modules",
    ".venv",
    "venv",
)

# Specific files whose whole body is inventory/routing-table content rather
# than prose — the YOK-N tokens inside are data, not historical provenance.
_EXEMPT_FILE_RELPATHS: frozenset[str] = frozenset({
    "packages/yoke-core/src/yoke_core/tools/shell_inventory.py",
    "packages/yoke-core/src/yoke_core/tools/shell_inventory_classify.py",
    "packages/yoke-core/src/yoke_core/tools/shell_inventory_report.py",
    "packages/yoke-core/src/yoke_core/tools/shell_inventory_rules.py",
    "packages/yoke-core/src/yoke_core/tools/shell_inventory_closeout.py",
})

_YOKE_REF = re.compile(r"YOK-(\d+)")

# YOK-N inside a TODO/FIXME/XXX/HACK marker is legitimate if the ticket
# is still open (status != done).
_TODO_LINE = re.compile(r"\b(?:TODO|FIXME|XXX|HACK)\b", re.IGNORECASE)

# ``def test_sun_N_*`` function names are explicitly allowed by AGENTS.md
# as a regression-test naming convention; the ticket ID is active state.
_TEST_FUNC_NAME = re.compile(r"def\s+test_sun_\d+", re.IGNORECASE)

# Quoted ticket literals (for example, ``"YOK-" + str(item_id)``) are test data, doc
# examples, CLI-usage snippets, or routing tables — not provenance. The
# HC-hardcoded-sun-ids check enforces the "no drifting IDs in tests" rule
# separately, so the cruft check focuses on inline provenance in comments
# and docstrings.
_QUOTED_YOKE_REF = re.compile(r"[\"']YOK-\d+[\"']")

# Regression-guard docstrings/comments may name the specific ticket they
# guard against — the ticket is active state (the bug being guarded).
_REGRESSION_GUARD_LINE = re.compile(
    r"\b(?:"
    r"[Rr]egression[- ]guard|"
    r"[Gg]uards?\s+(?:against\s+)?(?:the\s+)?YOK-|"
    r"[Rr]epro(?:duction|ducer)?\s+(?:of\s+|for\s+)?YOK-|"
    r"[Gg]uard\s+for\s+(?:the\s+)?YOK-|"
    r"[Pp]revent\s+regression\s+(?:of\s+)?YOK-"
    r")"
)


@dataclass
class CruftHit:
    path: Path
    line: int
    ticket: str
    status: str
    context: str


@dataclass
class LintResult:
    hits: list[CruftHit] = field(default_factory=list)
    scanned_files: int = 0
    ticket_lookups: int = 0
    unknown_tickets: set[str] = field(default_factory=set)


# ---------------------------------------------------------------------------
# Path discovery + exemptions
# ---------------------------------------------------------------------------


def _is_exempt(path: Path, *, repo_root: Optional[Path] = None) -> bool:
    for part in path.parts:
        if part in _EXEMPT_PATH_SEGMENTS:
            return True
    if repo_root is not None:
        try:
            rel = path.resolve().relative_to(repo_root.resolve())
        except ValueError:
            return False
        if str(rel) in _EXEMPT_FILE_RELPATHS:
            return True
    return False


def _iter_scan_paths(
    repo_root: Path,
    *,
    scan_dirs: Sequence[str] = _DEFAULT_SCAN_DIRS,
    root_files: Sequence[str] = _DEFAULT_SCAN_ROOT_FILES,
    extra_paths: Sequence[Path] = (),
) -> Iterable[Path]:
    for name in root_files:
        candidate = repo_root / name
        if candidate.is_file() and not _is_exempt(candidate, repo_root=repo_root):
            yield candidate
    for rel in scan_dirs:
        base = repo_root / rel
        if not base.is_dir():
            continue
        for ext in _SCAN_EXTS:
            for f in base.rglob(f"*{ext}"):
                if _is_exempt(f, repo_root=repo_root):
                    continue
                yield f
    for extra in extra_paths:
        p = Path(extra)
        if p.is_file() and p.suffix in _SCAN_EXTS and not _is_exempt(p, repo_root=repo_root):
            yield p
        elif p.is_dir():
            for ext in _SCAN_EXTS:
                for f in p.rglob(f"*{ext}"):
                    if _is_exempt(f, repo_root=repo_root):
                        continue
                    yield f


# ---------------------------------------------------------------------------
# Ticket status lookup
# ---------------------------------------------------------------------------


def _load_ticket_statuses(
    tickets: Iterable[str],
    *,
    db_path: Optional[str] = None,
) -> dict[str, str]:
    """Return a ``{ticket: status}`` map for every provided ticket.

    Missing tickets (already deleted or not yet filed) land in the map as
    ``'unknown'``. Opens a single read-only connection to minimise overhead.
    """
    ids = sorted({t for t in tickets if _YOKE_REF.fullmatch(t)})
    if not ids:
        return {}
    numeric_ids = [int(t.split("-", 1)[1]) for t in ids]

    statuses: dict[str, str] = {t: "unknown" for t in ids}
    try:
        conn = connect(path=db_path)
    except Exception:
        return statuses
    try:
        p = "%s" if db_backend.connection_is_postgres(conn) else "?"
        placeholders = ",".join([p] * len(numeric_ids))
        rows = conn.execute(
            f"SELECT id, status FROM items WHERE id IN ({placeholders})",
            numeric_ids,
        ).fetchall()
        for row in rows:
            row_id = row[0] if not hasattr(row, "keys") else row["id"]
            row_status = row[1] if not hasattr(row, "keys") else row["status"]
            ticket = f"YOK-{int(row_id)}"
            statuses[ticket] = str(row_status or "unknown")
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return statuses


# ---------------------------------------------------------------------------
# Core lint
# ---------------------------------------------------------------------------


def _python_exempt_line_ranges(text: str) -> set[int]:
    """Return 1-based line numbers where YOK-N occurrences are exempted.

    Ticket tokens inside *non-docstring* string literals are test data,
    routing-table values, CLI examples, etc. — not cold-start prose.
    Docstrings (first stmt of module/class/function) remain in scope
    because they accumulate historical provenance.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return set()
    docstring_lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(
            node,
            (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
        ):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if not isinstance(first, ast.Expr):
            continue
        val = first.value
        if not (isinstance(val, ast.Constant) and isinstance(val.value, str)):
            continue
        start = val.lineno
        end = val.end_lineno or start
        for ln in range(start, end + 1):
            docstring_lines.add(ln)

    exempt: set[int] = set()
    try:
        for t in tokenize.generate_tokens(io.StringIO(text).readline):
            if t.type != tokenize.STRING:
                continue
            sl, _ = t.start
            el, _ = t.end
            for ln in range(sl, el + 1):
                if ln in docstring_lines:
                    continue
                exempt.add(ln)
    except (tokenize.TokenizeError, IndentationError):
        return set()
    return exempt


def _line_is_allowed_context(line: str, status: str, ticket: str) -> bool:
    """Decide whether *line* is an allowed context for a YOK-N ref.

    Allowed regardless of ticket status: ``def test_sun_N_*`` function names
    and the specific ticket inside a quoted literal.
    Open-ticket references are additionally allowed inside TODO/FIXME.
    """
    if _TEST_FUNC_NAME.search(line):
        return True
    for quoted in _QUOTED_YOKE_REF.finditer(line):
        if ticket in quoted.group(0):
            return True
    if _REGRESSION_GUARD_LINE.search(line):
        return True
    if _TODO_LINE.search(line):
        return status != "done"
    return status != "done"


def scan(
    repo_root: Path,
    *,
    db_path: Optional[str] = None,
    extra_paths: Sequence[Path] = (),
) -> LintResult:
    """Scan *repo_root* for historical YOK-N cruft and return a :class:`LintResult`."""
    result = LintResult()

    tickets: set[str] = set()
    per_file_matches: list[tuple[Path, int, str, str]] = []

    for f in _iter_scan_paths(repo_root, extra_paths=extra_paths):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        result.scanned_files += 1
        exempt_lines: set[int] = set()
        if f.suffix == ".py":
            exempt_lines = _python_exempt_line_ranges(text)
        for i, line in enumerate(text.splitlines(), start=1):
            if i in exempt_lines:
                continue
            for match in _YOKE_REF.finditer(line):
                ticket = f"YOK-{match.group(1)}"
                tickets.add(ticket)
                per_file_matches.append((f, i, ticket, line.rstrip()))

    statuses = _load_ticket_statuses(tickets, db_path=db_path)
    result.ticket_lookups = len(statuses)

    for path, line_no, ticket, line in per_file_matches:
        status = statuses.get(ticket, "unknown")
        if status == "unknown":
            result.unknown_tickets.add(ticket)
            continue
        if status != "done":
            continue
        if _line_is_allowed_context(line, status, ticket):
            continue
        result.hits.append(
            CruftHit(
                path=path,
                line=line_no,
                ticket=ticket,
                status=status,
                context=line[:200],
            )
        )

    return result
