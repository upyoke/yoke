"""Scanner: product code never branches on a literal project name.

Product code runs for every install, so a comparison such as
``args.project == "yoke"`` or a SQL ``p.slug`` test against a quoted slug makes behavior differ
for every other project — and fails outright on an install that has no project
by that name. Each such branch stands in for a declared fact: a capability or
environment setting, the installation's own self project, or a property of
the project's checkout. Read that fact instead.

Flagged in shippable Python under :data:`SCAN_ROOTS`:

* a comparison (``==``, ``!=``, ``in``, ``not in``) between a project
  identifier — any name, attribute, or subscript key containing ``proj`` —
  and a slug-shaped string literal, or a collection of them;
* a comparison between any ``proj``/``slug``/``pid``/``namespace`` identifier
  and a registered project name;
* a registered project name bound to a ``project*`` keyword argument, to a
  ``*PROJECT*``/``*SLUG*`` name, or passed as a SQL parameter to a query call;
* SQL text comparing a slug column to a quoted literal.

Registered project names come from the caller (the doctor check reads the
``projects`` table), so the scan follows the installation, never a fixed list.
Named allowances for the remaining legitimate sites live in
:mod:`yoke_core.domain.lint_project_name_literal_allowances`.

Tests and fixtures are exempt: they name projects on purpose. Scope
sentinels (``all``, ``global``, ``null``, ...) are not project names.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Collection, Iterable, List, Optional, Tuple

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
_NAMED_IDENTIFIER_RE = re.compile(r"proj|slug|\bpid\b|namespace", re.IGNORECASE)
_NAMED_BINDING_RE = re.compile(r"proj|slug", re.IGNORECASE)
_QUERY_CALLS = frozenset(
    {
        "execute",
        "executemany",
        "query",
        "query_quiet",
        "query_rows",
        "query_scalar",
        "scalar",
    }
)
_SLUG_SHAPED_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
_SCOPE_SENTINELS = frozenset({"all", "global", "multi", "none", "null"})
_SQL_SLUG_COMPARISON_RE = re.compile(
    r"(?:\b(?:p|projects|owner|plan|proj\w*)\.slug"
    r"|\bFROM\s+projects\s+WHERE\s+slug)"
    r"\s*(?:=|<>|!=)\s*'([^']+)'",
    re.IGNORECASE,
)
_SQL_ANY_SLUG_COMPARISON_RE = re.compile(
    r"\bslug\s*(?:=|<>|!=)\s*'([^']+)'|'([^']+)'\s+as\s+\w*proj", re.IGNORECASE
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
    #: The identifier, keyword, or call the literal is bound to; allowances
    #: match on ``(relpath, subject)``.
    subject: str = ""


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


def _string_values(node: ast.AST) -> List[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, (ast.Set, ast.Tuple, ast.List)):
        return [
            element.value
            for element in node.elts
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        ]
    return []


def _comparison_hit(
    node: ast.Compare, names: Collection[str]
) -> Optional[Tuple[str, str]]:
    if len(node.ops) != 1 or not isinstance(
        node.ops[0], (ast.Eq, ast.NotEq, ast.In, ast.NotIn)
    ):
        return None
    left, right = node.left, node.comparators[0]
    for subject, other in ((left, right), (right, left)):
        identifier = _identifier(subject)
        if not identifier:
            continue
        literals = _project_name_literals(other)
        if not (literals and _PROJECT_IDENTIFIER_RE.search(identifier)):
            literals = [v for v in _string_values(other) if v in names]
            if not (literals and _NAMED_IDENTIFIER_RE.search(identifier)):
                continue
        found = f"{identifier} compared to {', '.join(map(repr, literals))}"
        return found, identifier
    return None


def _binding_hits(node: ast.AST, names: Collection[str]) -> List[Tuple[str, str]]:
    """Registered names bound to project keywords, constants, or SQL params."""
    found: List[Tuple[str, str]] = []
    if isinstance(node, ast.keyword) and node.arg:
        values = _string_values(node.value)
        if _NAMED_BINDING_RE.search(node.arg) and any(v in names for v in values):
            found.append((f"keyword {node.arg}={values[0]!r}", node.arg))
    elif isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        values = _string_values(node.value)
        if values and values[0] in names and isinstance(node.value, ast.Constant):
            for target in targets:
                name = _identifier(target)
                if name and _NAMED_BINDING_RE.search(name):
                    found.append((f"{name} = {values[0]!r}", name))
    elif isinstance(node, ast.Dict):
        for key, value in zip(node.keys, node.values):
            label = key.value if isinstance(key, ast.Constant) else ""
            values = _string_values(value) if isinstance(value, ast.Constant) else []
            if isinstance(label, str) and _NAMED_BINDING_RE.search(label):
                if values and values[0] in names:
                    found.append((f"{{{label!r}: {values[0]!r}}}", label))
    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        if _NAMED_BINDING_RE.search(node.name):
            for inner in ast.walk(node):
                if isinstance(inner, ast.Return) and inner.value is not None:
                    values = _string_values(inner.value)
                    if (
                        isinstance(inner.value, ast.Constant)
                        and values[:1]
                        and (values[0] in names)
                    ):
                        found.append(
                            (f"{node.name}() returns {values[0]!r}", node.name)
                        )
    elif isinstance(node, ast.Call):
        func = node.func
        call = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if _NAMED_BINDING_RE.search(call) and node.args:
            values = _string_values(node.args[0])
            if (
                isinstance(node.args[0], ast.Constant)
                and values[:1]
                and (values[0] in names)
            ):
                found.append((f"{call}({values[0]!r})", call))
        if call in _QUERY_CALLS:
            for arg in node.args:
                if isinstance(arg, (ast.Tuple, ast.List)):
                    hit = [v for v in _string_values(arg) if v in names]
                    if hit:
                        found.append((f"SQL parameter {hit[0]!r} to {call}()", call))
    return found


def scan_source(
    relpath: str, text: str, project_names: Collection[str] = ()
) -> List[ProjectLiteralHit]:
    """Every project-name branch in one Python source text."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    names = frozenset(project_names) - _SCOPE_SENTINELS
    hits: List[ProjectLiteralHit] = []
    for node in ast.walk(tree):
        line = getattr(node, "lineno", 0)
        if isinstance(node, ast.Compare):
            found = _comparison_hit(node, names)
            if found:
                hits.append(ProjectLiteralHit(relpath, line, found[0], found[1]))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            ends: set = set()
            for pattern, any_literal in (
                (_SQL_SLUG_COMPARISON_RE, True),
                (_SQL_ANY_SLUG_COMPARISON_RE, False),
            ):
                for match in pattern.finditer(node.value):
                    literal = next(group for group in match.groups() if group)
                    if match.end() in ends or literal in _SCOPE_SENTINELS:
                        continue
                    if not (any_literal or literal in names):
                        continue
                    ends.add(match.end())
                    snippet = f"SQL {match.group(0)!r}"
                    hits.append(ProjectLiteralHit(relpath, line, snippet, "SQL"))
        else:
            for snippet, subject in _binding_hits(node, names):
                lineno = getattr(node, "lineno", 0) or getattr(
                    getattr(node, "value", None), "lineno", 0
                )
                hits.append(ProjectLiteralHit(relpath, lineno, snippet, subject))
    return sorted(set(hits), key=lambda hit: (hit.line, hit.snippet))


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
    project_names: Collection[str] = (),
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
        relpath = path.relative_to(repo_root).as_posix()
        hits.extend(scan_source(relpath, text, project_names))
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
