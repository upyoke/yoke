"""Doctor HC: the product tree never depends on the private platform namespace.

The dependency direction across the product/platform boundary is one-way:
private platform code (Python namespace ``upyoke``) may import the public
product packages; nothing in this repository may import from, or declare a
packaging dependency on, that namespace. The check stays dormant while the
tree holds no such reference and fails the moment one lands — either an
import statement resolving into the namespace, or a pyproject requirement
naming a platform-owned distribution (``upyoke`` or an ``upyoke-*`` name).

Import detection is AST-based so string literals, comments, and doc prose
mentioning the namespace never trip it; sources that do not parse as Python
(e.g. Pack source carrying install placeholders) fall back to a line-level
import-statement scan.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

try:
    import tomllib
except ImportError:  # Python < 3.11
    tomllib = None

from yoke_core.api.repo_root import find_repo_root
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


HC_NAME = "HC-platform-namespace-boundary"
HC_DESC = (
    "Product tree must not import or declare a dependency on the "
    "private platform namespace"
)

# Python namespace owned by the private platform side of the boundary.
# Distributions named after it (exact or hyphen-prefixed) are platform-owned.
PRIVATE_PLATFORM_NAMESPACE = "upyoke"

# Directories holding tracked source, scanned recursively; top-level *.py
# files (e.g. the root conftest) are scanned in addition to these roots.
SCAN_ROOTS = ("docs", "packages", "packaging", "packs", "runtime", "tests")

# Line-level fallback for Python sources that fail to parse.
_FALLBACK_IMPORT_RE = re.compile(
    r"^\s*(?:import|from)\s+"
    + re.escape(PRIVATE_PLATFORM_NAMESPACE)
    + r"(?=[.\s]|$)"
)

_REQUIREMENT_NAME_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
_QUOTED_STRING_RE = re.compile(r"[\"']([^\"']+)[\"']")


@dataclass(frozen=True)
class PlatformNamespaceFinding:
    relpath: str
    line_no: int
    detail: str


def _project_root() -> Path:
    return find_repo_root(Path(__file__))


def _relpath(repo_root: Path, target: Path) -> str:
    try:
        return target.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return target.as_posix()


def _iter_python_files(repo_root: Path) -> Iterable[Path]:
    yield from sorted(repo_root.glob("*.py"))
    for rel in SCAN_ROOTS:
        base = repo_root / rel
        if base.is_dir():
            yield from sorted(base.rglob("*.py"))


def _iter_pyproject_files(repo_root: Path) -> Iterable[Path]:
    root_pyproject = repo_root / "pyproject.toml"
    if root_pyproject.is_file():
        yield root_pyproject
    for rel in SCAN_ROOTS:
        base = repo_root / rel
        if base.is_dir():
            yield from sorted(base.rglob("pyproject.toml"))


def _names_private_namespace(module: str) -> bool:
    return module == PRIVATE_PLATFORM_NAMESPACE or module.startswith(
        PRIVATE_PLATFORM_NAMESPACE + "."
    )


def _import_line_numbers(tree: ast.AST) -> List[int]:
    hits: List[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(_names_private_namespace(alias.name) for alias in node.names):
                hits.append(node.lineno)
        elif isinstance(node, ast.ImportFrom):
            if (
                node.level == 0
                and node.module
                and _names_private_namespace(node.module)
            ):
                hits.append(node.lineno)
    return hits


def scan_python_imports(repo_root: Path) -> List[PlatformNamespaceFinding]:
    """Return Python imports that reach into the private platform namespace."""
    findings: List[PlatformNamespaceFinding] = []
    for source in _iter_python_files(repo_root):
        try:
            text = source.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if PRIVATE_PLATFORM_NAMESPACE not in text:
            continue
        lines = text.splitlines()
        try:
            line_numbers = _import_line_numbers(ast.parse(text))
        except SyntaxError:
            line_numbers = [
                line_no
                for line_no, line in enumerate(lines, start=1)
                if _FALLBACK_IMPORT_RE.match(line)
            ]
        relpath = _relpath(repo_root, source)
        for line_no in line_numbers:
            detail = lines[line_no - 1].strip() if line_no <= len(lines) else ""
            findings.append(PlatformNamespaceFinding(relpath, line_no, detail))
    return findings


def _is_platform_distribution(requirement: str) -> bool:
    match = _REQUIREMENT_NAME_RE.match(requirement)
    if not match:
        return False
    name = re.sub(r"[-_.]+", "-", match.group(1)).lower()
    return name == PRIVATE_PLATFORM_NAMESPACE or name.startswith(
        PRIVATE_PLATFORM_NAMESPACE + "-"
    )


def _requirement_strings(data: object) -> List[str]:
    if not isinstance(data, dict):
        return []
    groups: List[object] = []
    project = data.get("project", {})
    if isinstance(project, dict):
        groups.append(project.get("dependencies", []))
        optional = project.get("optional-dependencies", {})
        if isinstance(optional, dict):
            groups.extend(optional.values())
    build_system = data.get("build-system", {})
    if isinstance(build_system, dict):
        groups.append(build_system.get("requires", []))
    dependency_groups = data.get("dependency-groups", {})
    if isinstance(dependency_groups, dict):
        groups.extend(dependency_groups.values())
    return [
        entry
        for group in groups
        if isinstance(group, list)
        for entry in group
        if isinstance(entry, str)
    ]


def scan_pyproject_dependencies(
    repo_root: Path,
) -> List[PlatformNamespaceFinding]:
    """Return pyproject requirements naming a platform-owned distribution."""
    findings: List[PlatformNamespaceFinding] = []
    for pyproject in _iter_pyproject_files(repo_root):
        try:
            text = pyproject.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # PEP 503 requirement names are case-insensitive, so the cheap
        # pre-filter must compare against lowered text (the Python import
        # scan stays case-sensitive: module names are).
        if PRIVATE_PLATFORM_NAMESPACE not in text.lower():
            continue
        if tomllib is None:
            requirements = _QUOTED_STRING_RE.findall(text)
        else:
            try:
                requirements = _requirement_strings(tomllib.loads(text))
            except tomllib.TOMLDecodeError:
                requirements = _QUOTED_STRING_RE.findall(text)
        relpath = _relpath(repo_root, pyproject)
        lines = text.splitlines()
        for requirement in requirements:
            if not _is_platform_distribution(requirement):
                continue
            line_no = next(
                (
                    number
                    for number, line in enumerate(lines, start=1)
                    if requirement in line
                ),
                0,
            )
            findings.append(
                PlatformNamespaceFinding(
                    relpath, line_no, f'dependency "{requirement}"'
                )
            )
    return findings


def scan_platform_namespace_boundary(
    repo_root: Path,
) -> List[PlatformNamespaceFinding]:
    """Return every product-tree reference into the private platform namespace."""
    return scan_python_imports(repo_root) + scan_pyproject_dependencies(repo_root)


def hc_platform_namespace_boundary(
    conn, args: DoctorArgs, rec: RecordCollector,
) -> None:
    """Doctor entry. FAILs when product code references the platform namespace."""
    del conn, args
    findings = scan_platform_namespace_boundary(_project_root())
    if not findings:
        rec.record(
            HC_NAME,
            HC_DESC,
            "PASS",
            "No Python import or pyproject dependency references the private "
            f"platform namespace ({PRIVATE_PLATFORM_NAMESPACE}).",
        )
        return
    head = (
        f"- {len(findings)} reference(s) point from the product tree into the "
        f"private platform namespace ({PRIVATE_PLATFORM_NAMESPACE}). The "
        "dependency direction is one-way: platform code may import product "
        "packages, never the reverse. Invert or remove the reference."
    )
    body = "\n".join(
        [head, ""]
        + [f"  - `{f.relpath}:{f.line_no}` {f.detail}" for f in findings]
    )
    rec.record(HC_NAME, HC_DESC, "FAIL", body)


__all__ = [
    "HC_NAME",
    "HC_DESC",
    "PRIVATE_PLATFORM_NAMESPACE",
    "SCAN_ROOTS",
    "PlatformNamespaceFinding",
    "hc_platform_namespace_boundary",
    "scan_platform_namespace_boundary",
    "scan_pyproject_dependencies",
    "scan_python_imports",
]
