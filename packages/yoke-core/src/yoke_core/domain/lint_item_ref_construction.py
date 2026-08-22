"""Scanners: item refs are formatted and parsed only by the canonical helpers.

A public item ref is display-only — ``{public_item_prefix}-{project_sequence}``
— and is produced solely by the canonical helpers
(``yoke_contracts.item_ref.format_item_ref`` /
``yoke_core.domain.project_identity.render_item_ref``). Internal code addresses
items by the bare integer ``items.id`` and resolves a user token back to an id
via ``project_identity.resolve_item_id`` — never by stripping a prefix.

Building a ref inline (``f"YOK-{x}"``) or parsing one back
(``x.replace("YOK-", "")``) hardcodes the prefix (wrong for the ``BUZ`` / ``PLAT``
projects) and, when built from an internal id, prints the wrong number
(``items.id`` instead of ``project_sequence``). Those two shapes are exactly
what let a fabricated ref like ``YOK-1915`` reach the operator.

Two scans keep both directions closed. :func:`scan` flags any *literal*
ref-prefix token in Python source outside the canonical formatter/resolver and
tests; the canonical helpers format from a *variable* prefix
(``f"{prefix}-{seq}"``) and so never trip it. :func:`scan_parser_policy` flags
the read direction: an implicit ``allow_bare_internal=True`` opt-out, a
project-blind prefix regex, or a numeric-tail coercion, each of which reads an
operator's token as an internal id. Both carry exact-path allowances, and
:func:`stale_parser_policy_allowances` reports the ones whose legacy read is
gone so the allowances shrink with the code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, List, Optional, Sequence, Tuple

# Roots that hold shippable Python source. Prose (``*.md``) is the domain of
# ``HC-historical-yok-n-cruft``; this scanner is code-only.
_SCAN_ROOTS: Tuple[str, ...] = ("packages", "runtime")

# Path substrings that mark a file as out of scope. Tests and fixtures author
# synthetic refs on purpose; build trees are generated copies.
_EXEMPT_SEGMENTS: Tuple[str, ...] = (
    "/build/",
    "/tests/",
    "/fixtures/",
    "/.venv/",
)

# Repo-relative POSIX paths where a ref-prefix literal is legitimate: the
# canonical formatter/resolver themselves, and the ref-scanning meta-modules
# (which carry the token as scan patterns, not as constructed refs). This is the
# whole allowlist — keep it small and explicit.
_EXEMPT_RELPATHS: frozenset[str] = frozenset(
    {
        "packages/yoke-contracts/src/yoke_contracts/item_ref.py",
        "packages/yoke-core/src/yoke_core/domain/project_identity.py",
        "packages/yoke-core/src/yoke_core/domain/project_identity_item_ref.py",
        "packages/yoke-core/src/yoke_core/domain/yok_n_parser.py",
        "packages/yoke-core/src/yoke_core/domain/worktree_naming.py",
        "packages/yoke-core/src/yoke_core/domain/lint_item_ref_construction.py",
        "packages/yoke-core/src/yoke_core/domain/item_ref_construction_baseline.py",
        "packages/yoke-core/src/yoke_core/domain/lint_yok_n_cruft.py",
        "packages/yoke-core/src/yoke_core/domain/lint_yok_n_cruft_scan.py",
        "packages/yoke-core/src/yoke_core/engines/check_item_ref_construction.py",
        "packages/yoke-core/src/yoke_core/engines/check_historical_yok_n.py",
    }
)

_IMPLICIT_INTERNAL_RE = re.compile(r"\ballow_bare_internal\s*=\s*True\b")
_PREFIX_CLASS_STRIP_RE = re.compile(r"(?:\[[A-Za-z]{2}\]){2,}[^'\"]*-")
_GENERIC_PREFIX_PARSE_RE = re.compile(
    r"\^\[A-Za-z\]\[A-Za-z0-9\]\*?-"
)
_NUMERIC_TAIL_ACCESS_PATTERN = (
    r"\.(?:r?split)\(\s*['\"]-['\"]\s*,\s*1\s*\)\s*\[\s*-?1\s*\]"
)
_NUMERIC_TAIL_ACCESS_RE = re.compile(_NUMERIC_TAIL_ACCESS_PATTERN)
_NUMERIC_TAIL_COERCION_RE = re.compile(
    rf"(?:\bint\([^#\n]*{_NUMERIC_TAIL_ACCESS_PATTERN}[^#\n]*\)"
    rf"|{_NUMERIC_TAIL_ACCESS_PATTERN}\s*\.isdigit\(\))"
)

# These modules consume stored pre-cutover item tokens, not operator input.
# Each path stays visible here so removing its legacy read also removes a stale
# allowance enforced by ``stale_parser_policy_allowances``.
_NUMERIC_TAIL_ALLOWLIST: dict[str, str] = {
    "packages/yoke-core/src/yoke_core/domain/item_ref_columns.py": (
        "legacy dependency-column compatibility on incomplete schemas"
    ),
    "packages/yoke-core/src/yoke_core/domain/migrations/"
    "_numeric_item_dependency_ids.py": "frozen migration of stored item tokens",
}
_IMPLICIT_INTERNAL_ALLOWLIST: dict[str, str] = {
    "packages/yoke-core/src/yoke_core/domain/item_ref_columns.py": (
        "legacy textual dependency-column reader"
    ),
}


def _is_test_file(rel_posix: str) -> bool:
    name = rel_posix.rsplit("/", 1)[-1]
    return (
        name.startswith("test_")
        or name.endswith("_test.py")
        or name == "conftest.py"
        or name.endswith("_test_helpers.py")
        or name.endswith("_test_support.py")
    )


def _is_exempt(rel_posix: str) -> bool:
    if rel_posix in _EXEMPT_RELPATHS:
        return True
    if _is_test_file(rel_posix):
        return True
    return any(seg in f"/{rel_posix}" for seg in _EXEMPT_SEGMENTS)


def _build_pattern(prefixes: Sequence[str]) -> Optional[re.Pattern[str]]:
    """One alternation matching a literal ref-prefix token for any prefix.

    Two shapes per prefix ``P``:
      * ``P-{``          — f-string construction (``f"YOK-{item_id}"``)
      * ``"P-"`` / ``'P-'`` — a bare prefix literal, which is how both string
        concatenation (``"YOK-" + n``) and parse-back
        (``.replace("YOK-", "")`` / ``.removeprefix("YOK-")``) spell it.
    """
    escaped = [re.escape(p) for p in prefixes if p]
    if not escaped:
        return None
    alt = "|".join(escaped)
    return re.compile(rf"(?:(?:{alt})-\{{)|(?:['\"](?:{alt})-['\"])")


@dataclass(frozen=True)
class RefLiteralHit:
    path: Path
    line: int
    snippet: str


def scan(
    repo_root: Path,
    prefixes: Iterable[str],
) -> List[RefLiteralHit]:
    """Return every literal ref-prefix hit in scannable Python source.

    ``prefixes`` is the live set of ``projects.public_item_prefix`` values; the
    caller (the HC) resolves it from the DB so no prefix is hardcoded here.
    """
    pattern = _build_pattern(list(prefixes))
    if pattern is None:
        return []
    root = repo_root.resolve()
    hits: List[RefLiteralHit] = []
    for scan_root in _SCAN_ROOTS:
        base = root / scan_root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            try:
                rel = path.resolve().relative_to(root).as_posix()
            except ValueError:
                continue
            if _is_exempt(rel):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if "-{" not in text and "-'" not in text and '-"' not in text:
                continue
            for lineno, raw in enumerate(text.splitlines(), start=1):
                if pattern.search(raw):
                    hits.append(
                        RefLiteralHit(
                            path=path.resolve(),
                            line=lineno,
                            snippet=raw.strip()[:160],
                        )
                    )
    return hits


def scan_parser_policy(repo_root: Path) -> List[RefLiteralHit]:
    """Return implicit-internal opt-outs and project-blind regex parsers."""
    root = repo_root.resolve()
    hits: List[RefLiteralHit] = []
    for scan_root in _SCAN_ROOTS:
        base = root / scan_root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            try:
                rel = path.resolve().relative_to(root).as_posix()
            except ValueError:
                continue
            if _is_exempt(rel):
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            for lineno, raw in enumerate(lines, start=1):
                implicit_internal = _IMPLICIT_INTERNAL_RE.search(raw)
                numeric_tail = _NUMERIC_TAIL_COERCION_RE.search(raw)
                if (
                    (
                        implicit_internal
                        and rel not in _IMPLICIT_INTERNAL_ALLOWLIST
                    )
                    or _PREFIX_CLASS_STRIP_RE.search(raw)
                    or _GENERIC_PREFIX_PARSE_RE.search(raw)
                    or (numeric_tail and rel not in _NUMERIC_TAIL_ALLOWLIST)
                ):
                    hits.append(
                        RefLiteralHit(path.resolve(), lineno, raw.strip()[:160])
                    )
    return hits


def stale_parser_policy_allowances(repo_root: Path) -> List[str]:
    """Return allowances whose exact legacy read has disappeared."""
    root = repo_root.resolve()
    stale: List[str] = []
    allowed_paths = _NUMERIC_TAIL_ALLOWLIST.keys() | _IMPLICIT_INTERNAL_ALLOWLIST.keys()
    for rel in sorted(allowed_paths):
        path = root / rel
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            stale.append(rel)
            continue
        numeric_stale = (
            rel in _NUMERIC_TAIL_ALLOWLIST
            and _NUMERIC_TAIL_ACCESS_RE.search(text) is None
        )
        internal_stale = (
            rel in _IMPLICIT_INTERNAL_ALLOWLIST
            and _IMPLICIT_INTERNAL_RE.search(text) is None
        )
        if numeric_stale or internal_stale:
            stale.append(rel)
    return stale


def counts_by_relpath(
    repo_root: Path,
    hits: Sequence[RefLiteralHit],
) -> dict[str, int]:
    """Aggregate hits into ``{repo-relative-posix-path: count}`` for the ratchet."""
    root = repo_root.resolve()
    out: dict[str, int] = {}
    for hit in hits:
        try:
            rel = hit.path.relative_to(root).as_posix()
        except ValueError:
            rel = hit.path.as_posix()
        out[rel] = out.get(rel, 0) + 1
    return out


def resolve_project_prefixes(conn: Any) -> List[str]:
    """Live ``projects.public_item_prefix`` set — the authority, never hardcoded."""
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT DISTINCT public_item_prefix FROM projects "
            "WHERE public_item_prefix IS NOT NULL"
        ).fetchall()
    except Exception:
        return []
    prefixes: List[str] = []
    for row in rows:
        try:
            value = row["public_item_prefix"]
        except (KeyError, TypeError, IndexError):
            value = row[0]
        text = str(value or "").strip()
        if text:
            prefixes.append(text)
    return prefixes
