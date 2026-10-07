"""Scanner: product code never branches on a literal project name.

Product code runs for every install, so a comparison such as
``args.project == "yoke"`` or a SQL ``p.slug`` test against a quoted slug makes behavior differ
for every other project — and fails outright on an install that has no project
by that name. Each such branch stands in for a declared fact: a capability or
environment setting, the installation's own self project, or a property of
the project's checkout. Read that fact instead.

Two shapes are flagged in shippable Python under :data:`SCAN_ROOTS`:

* a comparison (``==``, ``!=``, ``in``, ``not in``) between a project
  identifier — any name, attribute, or subscript key containing ``proj`` —
  and a slug-shaped string literal, or a collection of them;
* SQL text comparing a projects slug column (``p.slug``, ``projects.slug``,
  ``owner.slug``, ``plan.slug``, or ``FROM projects WHERE slug``) to a quoted
  literal.

Tests and fixtures are exempt: they name projects on purpose. Scope
sentinels (``all``, ``global``, ``null``, ...) are not project names.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Tuple

SCAN_ROOTS: Tuple[str, ...] = ("packages", "runtime")

_EXEMPT_SEGMENTS: Tuple[str, ...] = (
    "/build/",
    "/tests/",
    "/fixtures/",
    "/install_bundle_tree/",
    "/.venv/",
)
_TEST_FILE_RE = re.compile(
    r"^(?:test_.*|conftest|.*_tests?_.*|.*_tests?|.*fixtures?.*|.*test_helpers.*"
    r"|.*test_support.*)\.py$"
)
_PROJECT_IDENTIFIER_RE = re.compile(r"proj", re.IGNORECASE)
_SLUG_SHAPED_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
_SCOPE_SENTINELS = frozenset({"all", "global", "multi", "none", "null"})
_SQL_SLUG_COMPARISON_RE = re.compile(
    r"(?:\b(?:p|projects|owner|plan|proj\w*)\.slug"
    r"|\bFROM\s+projects\s+WHERE\s+slug)"
    r"\s*(?:=|<>|!=)\s*'([^']+)'",
    re.IGNORECASE,
)
_UNWRAP_CALLS = frozenset({"str", "lower", "strip", "casefold"})

RECOVERY = (
    "Replace the literal with the declared fact it stands in for: a project "
    "capability or environment setting, the installation's self project "
    "(yoke_core.engines.doctor_context.resolve_self_project), the checkout's "
    "own project (default_project_for_directory), or a property of the "
    "checkout (is_yoke_source_checkout). Name the project in a test or "
    "fixture instead when the comparison is test scaffolding."
)


@dataclass(frozen=True)
class ProjectLiteralHit:
    """One project-name branch found in product code."""

    relpath: str
    line: int
    snippet: str


def is_exempt_relpath(relpath: str) -> bool:
    """Whether *relpath* is test scaffolding or a generated copy."""
    rel = "/" + relpath
    if any(segment in rel for segment in _EXEMPT_SEGMENTS):
        return True
    return bool(_TEST_FILE_RE.match(relpath.rsplit("/", 1)[-1]))


def _identifier(node: ast.AST) -> str:
    """Dotted text of a name/attribute/subscript chain, or ``""``."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_identifier(node.value)}.{node.attr}"
    if isinstance(node, ast.Subscript):
        key = node.slice
        text = key.value if isinstance(key, ast.Constant) else ""
        return f"{_identifier(node.value)}[{text}]"
    if isinstance(node, ast.Call):
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        if name in _UNWRAP_CALLS:
            if isinstance(func, ast.Attribute):
                return _identifier(func.value)
            if node.args:
                return _identifier(node.args[0])
    return ""


def _project_name_literals(node: ast.AST) -> List[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        values = [node.value]
    elif isinstance(node, (ast.Set, ast.Tuple, ast.List)):
        values = [
            element.value
            for element in node.elts
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        ]
    else:
        return []
    return [
        value
        for value in values
        if _SLUG_SHAPED_RE.match(value) and value not in _SCOPE_SENTINELS
    ]


def _comparison_hit(node: ast.Compare) -> Optional[str]:
    if len(node.ops) != 1 or not isinstance(
        node.ops[0], (ast.Eq, ast.NotEq, ast.In, ast.NotIn)
    ):
        return None
    left, right = node.left, node.comparators[0]
    for subject, other in ((left, right), (right, left)):
        identifier = _identifier(subject)
        literals = _project_name_literals(other)
        if identifier and literals and _PROJECT_IDENTIFIER_RE.search(identifier):
            return f"{identifier} compared to {', '.join(map(repr, literals))}"
    return None


def scan_source(relpath: str, text: str) -> List[ProjectLiteralHit]:
    """Every project-name branch in one Python source text."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    hits: List[ProjectLiteralHit] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            found = _comparison_hit(node)
            if found:
                hits.append(ProjectLiteralHit(relpath, node.lineno, found))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            for match in _SQL_SLUG_COMPARISON_RE.finditer(node.value):
                if match.group(1) not in _SCOPE_SENTINELS:
                    hits.append(
                        ProjectLiteralHit(
                            relpath, node.lineno, f"SQL {match.group(0)!r}"
                        )
                    )
    return sorted(hits, key=lambda hit: hit.line)


def source_paths(repo_root: Path) -> Iterable[Path]:
    """Shippable Python files under :data:`SCAN_ROOTS`."""
    for name in SCAN_ROOTS:
        for path in sorted((repo_root / name).rglob("*.py")):
            relpath = path.relative_to(repo_root).as_posix()
            if not is_exempt_relpath(relpath):
                yield path


def scan(
    repo_root: Path,
    *,
    read_text: Optional[Callable[[Path], str]] = None,
) -> List[ProjectLiteralHit]:
    """Every project-name branch in the product code under *repo_root*."""
    reader = read_text or (lambda path: path.read_text(encoding="utf-8"))
    hits: List[ProjectLiteralHit] = []
    for path in source_paths(repo_root):
        try:
            text = reader(path)
        except (OSError, UnicodeDecodeError):
            continue
        hits.extend(scan_source(path.relative_to(repo_root).as_posix(), text))
    return hits


__all__ = [
    "ProjectLiteralHit",
    "RECOVERY",
    "SCAN_ROOTS",
    "is_exempt_relpath",
    "scan",
    "scan_source",
    "source_paths",
]
