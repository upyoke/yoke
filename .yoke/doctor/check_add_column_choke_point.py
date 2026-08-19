"""Doctor HC: additive columns enter through the catalog-then-add helper.

Postgres still takes an exclusive lock for ``ADD COLUMN IF NOT EXISTS`` when
the column is already visible in catalogs. The only sanctioned add path is
:func:`yoke_core.domain.schema_common._add_column_if_not_exists`, which
looks up the column and issues ``ADD COLUMN`` only when it is missing.

This check scans executable string literals in tracked non-test Python and
SQL. Docstrings, comments, and named throwaway-database test fixtures are
out of scope so a prose mention cannot be "fixed" by rewording docs.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional, Sequence

from yoke_core.api.repo_root import find_repo_root
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


HC_NAME = "HC-add-column-choke-point"
HC_DESC = (
    "Executable ADD COLUMN IF NOT EXISTS must go through the "
    "catalog-then-add helper"
)

CHOKE_POINT = "packages/yoke-core/src/yoke_core/domain/schema_common.py"
SCAN_ROOTS = ("packages", "runtime")
GENERATED_TREE_NAMES = frozenset({"build", "dist"})
EXEMPT_RELPATHS = frozenset(
    {
        CHOKE_POINT,
        "runtime/api/merge_worktree_test_db.py",
        ".yoke/doctor/check_add_column_choke_point.py",
    }
)
_PHRASE_RE = re.compile(r"ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS", re.IGNORECASE)
_SQL_LINE_COMMENT_RE = re.compile(r"--[^\n]*")
_SQL_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)


@dataclass(frozen=True)
class RawAddColumn:
    """One executable lock-taking add-column form outside the helper."""

    relpath: str
    line: int


def _project_root() -> Path:
    return find_repo_root(Path(__file__))


def _is_test_path(relative: Path) -> bool:
    name = relative.name
    if name.startswith("test_") or name.endswith("_test.py"):
        return True
    if name == "conftest.py":
        return True
    return "tests" in relative.parts


def _docstring_nodes(tree: ast.AST) -> set[int]:
    nodes: set[int] = set()

    def _first_string(body: list[ast.stmt]) -> None:
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            nodes.add(id(body[0].value))

    if isinstance(tree, ast.Module):
        _first_string(tree.body)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            _first_string(node.body)
    return nodes


def _literal_strings(tree: ast.AST) -> Iterator[tuple[int, str]]:
    docstrings = _docstring_nodes(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in docstrings:
                continue
            yield node.lineno, node.value
        elif isinstance(node, ast.JoinedStr):
            parts = [
                value.value
                for value in node.values
                if isinstance(value, ast.Constant) and isinstance(value.value, str)
            ]
            if parts:
                yield node.lineno, "".join(parts)


def _scan_python(repo_root: Path, path: Path) -> List[RawAddColumn]:
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return []
    if "IF NOT EXISTS" not in source.upper():
        return []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    relpath = path.relative_to(repo_root).as_posix()
    return [
        RawAddColumn(relpath=relpath, line=lineno)
        for lineno, text in _literal_strings(tree)
        if _PHRASE_RE.search(text)
    ]


def _sql_executable_text(source: str) -> str:
    stripped = _SQL_BLOCK_COMMENT_RE.sub(" ", source)
    return _SQL_LINE_COMMENT_RE.sub(" ", stripped)


def _scan_sql(repo_root: Path, path: Path) -> List[RawAddColumn]:
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return []
    executable = _sql_executable_text(source)
    if not _PHRASE_RE.search(executable):
        return []
    relpath = path.relative_to(repo_root).as_posix()
    findings: List[RawAddColumn] = []
    for lineno, line in enumerate(source.splitlines(), start=1):
        if _PHRASE_RE.search(_sql_executable_text(line)):
            findings.append(RawAddColumn(relpath=relpath, line=lineno))
    return findings


def _scanned_files(repo_root: Path, roots: Sequence[str]) -> Iterator[Path]:
    for root in roots:
        base = repo_root / root
        if not base.is_dir():
            continue
        for path in sorted((*base.rglob("*.py"), *base.rglob("*.sql"))):
            relative = path.relative_to(repo_root)
            if GENERATED_TREE_NAMES.intersection(relative.parts):
                continue
            if _is_test_path(relative):
                continue
            if relative.as_posix() in EXEMPT_RELPATHS:
                continue
            yield path


def scan_raw_add_column_if_not_exists(
    repo_root: Path,
    *,
    roots: Optional[Sequence[str]] = None,
) -> List[RawAddColumn]:
    """Return executable lock-taking add-column forms outside the helper."""
    findings: List[RawAddColumn] = []
    for path in _scanned_files(repo_root, roots if roots is not None else SCAN_ROOTS):
        if path.suffix == ".sql":
            findings.extend(_scan_sql(repo_root, path))
        else:
            findings.extend(_scan_python(repo_root, path))
    return findings


def hc_add_column_choke_point(
    conn,
    args: DoctorArgs,
    rec: RecordCollector,
) -> None:
    """Doctor entry. FAILs when executable source bypasses the helper."""
    findings = scan_raw_add_column_if_not_exists(_project_root())
    if not findings:
        rec.record(
            HC_NAME,
            HC_DESC,
            "PASS",
            "Executable add-column forms go through the catalog-then-add helper.",
        )
        return
    head = (
        f"- {len(findings)} executable statement(s) emit "
        "`ADD COLUMN IF NOT EXISTS` outside "
        "`schema_common._add_column_if_not_exists`. Route the column through "
        "that helper so catalogs already seeing it do not take an exclusive lock."
    )
    body = "\n".join([head, ""] + [f"  - `{f.relpath}:{f.line}`" for f in findings])
    rec.record(HC_NAME, HC_DESC, "FAIL", body)


__all__ = [
    "CHOKE_POINT",
    "EXEMPT_RELPATHS",
    "GENERATED_TREE_NAMES",
    "HC_DESC",
    "HC_NAME",
    "RawAddColumn",
    "SCAN_ROOTS",
    "hc_add_column_choke_point",
    "scan_raw_add_column_if_not_exists",
]

from yoke_project_checks._declare import (  # noqa: E402
    self_project_checks,
)

PROJECT_HEALTH_CHECKS = self_project_checks(
    (
        "add-column-choke-point",
        "Executable ADD COLUMN IF NOT EXISTS must go through the "
        "catalog-then-add helper",
        hc_add_column_choke_point,
    ),
)
