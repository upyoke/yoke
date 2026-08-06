"""Doctor HC: the ambient authority is opened only through the guarded factory.

``db_backend.connect`` and the no-DSN form of ``db_backend.connect_psycopg``
refuse to open a connection where the active control plane is reached over
https, because there is no local database there to open. That refusal is what
makes a bare connection on a client-reachable path fail at the call site
instead of silently skipping a write.

The refusal only holds for callers that go through those two functions. Handing
the ambient authority resolver straight to the driver —
``psycopg.connect(db_backend.resolve_pg_dsn())`` — opens the same connection
with the guard bypassed, and no test can catch it because the bypass is exactly
what stops the guard from firing.

So the invariant is composition, not any single symbol: ``psycopg.connect`` may
be handed ``resolve_pg_dsn()`` only inside the guarded factory itself, or under
an explicit ``local_authority_exempt()`` block. The block is the named
exception mechanism — the same one the runtime guard reads — so a legitimate
direct connection declares itself at the call site instead of being listed
somewhere that rots as files move.

Out of scope by construction: ``psycopg.connect(some_explicit_dsn)`` names a
specific database (a migration validation surface, a maintenance connection,
another cluster member) rather than acquiring the ambient authority, so it is
not the connection this guard is about.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional, Sequence

from yoke_core.api.repo_root import find_repo_root
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


HC_NAME = "HC-ambient-authority-connection-guard"
HC_DESC = (
    "Raw driver connections to the ambient Postgres authority must go through "
    "the guarded factory or declare local_authority_exempt()"
)

#: The connection factory that owns the guard; the composition is its job.
GUARDED_FACTORY = "packages/yoke-core/src/yoke_core/domain/db_backend.py"

#: Roots scanned for the composition. Tests are excluded: a test that opens a
#: database directly is exercising the machinery, not shipping a call path.
SCAN_ROOTS = ("packages", "runtime")

#: Generated Python trees repeat package source and are not shipping call paths.
GENERATED_TREE_NAMES = frozenset({"build", "dist"})

DRIVER_MODULE = "psycopg"
DRIVER_CONNECT = "connect"
AMBIENT_RESOLVER = "resolve_pg_dsn"
EXEMPTION = "local_authority_exempt"


@dataclass(frozen=True)
class UnguardedConnection:
    """One raw driver connection to the ambient authority, undeclared."""

    relpath: str
    line: int


def _project_root() -> Path:
    return find_repo_root(Path(__file__))


def _called_name(node: ast.AST) -> str:
    """Return the trailing name of a call target, or '' for anything else."""
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _is_driver_connect(call: ast.Call, bare_connect_is_driver: bool) -> bool:
    func = call.func
    if isinstance(func, ast.Attribute):
        return (
            func.attr == DRIVER_CONNECT
            and isinstance(func.value, ast.Name)
            and func.value.id == DRIVER_MODULE
        )
    if isinstance(func, ast.Name):
        return bare_connect_is_driver and func.id == DRIVER_CONNECT
    return False


def _imports_driver_connect_bare(tree: ast.Module) -> bool:
    """Whether the module did ``from psycopg import connect``."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == DRIVER_MODULE:
            if any(alias.name == DRIVER_CONNECT for alias in node.names):
                return True
    return False


def _resolves_ambient_authority(call: ast.Call) -> bool:
    """Whether any argument of *call* calls the ambient authority resolver."""
    for argument in list(call.args) + [kw.value for kw in call.keywords]:
        for node in ast.walk(argument):
            if isinstance(node, ast.Call):
                if _called_name(node.func) == AMBIENT_RESOLVER:
                    return True
    return False


def _declares_exemption(statement: ast.With) -> bool:
    for item in statement.items:
        expression = item.context_expr
        if isinstance(expression, ast.Call):
            if _called_name(expression.func) == EXEMPTION:
                return True
    return False


def _unguarded_calls(tree: ast.Module) -> Iterator[ast.Call]:
    """Yield ambient-authority driver connects not inside an exemption block.

    Walks the tree carrying whether an enclosing ``with`` already declares the
    exemption, so nesting depth does not matter — a declaration anywhere above
    the call covers it, and a declaration elsewhere in the file does not.
    """
    bare_is_driver = _imports_driver_connect_bare(tree)

    def visit(node: ast.AST, exempt: bool) -> Iterator[ast.Call]:
        if isinstance(node, ast.With) and _declares_exemption(node):
            exempt = True
        if (
            isinstance(node, ast.Call)
            and not exempt
            and _is_driver_connect(node, bare_is_driver)
            and _resolves_ambient_authority(node)
        ):
            yield node
        for child in ast.iter_child_nodes(node):
            yield from visit(child, exempt)

    yield from visit(tree, False)


def _scan_one(repo_root: Path, path: Path) -> List[UnguardedConnection]:
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return []
    # Cheap reject before paying for a parse: the composition needs both names.
    if AMBIENT_RESOLVER not in source or DRIVER_CONNECT not in source:
        return []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    relpath = path.relative_to(repo_root).as_posix()
    return [
        UnguardedConnection(relpath=relpath, line=call.lineno)
        for call in _unguarded_calls(tree)
    ]


def _scanned_files(repo_root: Path, roots: Sequence[str]) -> Iterator[Path]:
    for root in roots:
        base = repo_root / root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            relative = path.relative_to(repo_root)
            if GENERATED_TREE_NAMES.intersection(relative.parts):
                continue
            if path.name.startswith("test_"):
                continue
            if relative.as_posix() == GUARDED_FACTORY:
                continue
            yield path


def scan_for_unguarded_connections(
    repo_root: Path,
    *,
    roots: Optional[Sequence[str]] = None,
) -> List[UnguardedConnection]:
    """Return every undeclared raw driver connect to the ambient authority."""
    findings: List[UnguardedConnection] = []
    for path in _scanned_files(repo_root, roots if roots is not None else SCAN_ROOTS):
        findings.extend(_scan_one(repo_root, path))
    return findings


def hc_ambient_authority_connection_guard(
    conn,
    args: DoctorArgs,
    rec: RecordCollector,
) -> None:
    """Doctor entry. FAILs on an undeclared raw connect to the ambient authority."""
    findings = scan_for_unguarded_connections(_project_root())
    if not findings:
        rec.record(
            HC_NAME,
            HC_DESC,
            "PASS",
            "Every raw driver connection to the ambient Postgres authority is "
            "either inside the guarded factory or declared exempt.",
        )
        return
    head = (
        f"- {len(findings)} raw driver connection(s) acquire the ambient "
        "Postgres authority without the guard that refuses it where the "
        "control plane is remote. Open it through `db_backend.connect()`, or "
        "— if this really does mean to open a local database it holds "
        "authority over — wrap the call in "
        "`yoke_contracts.control_plane_locality.local_authority_exempt()`."
    )
    body = "\n".join([head, ""] + [f"  - `{f.relpath}:{f.line}`" for f in findings])
    rec.record(HC_NAME, HC_DESC, "FAIL", body)


__all__ = [
    "AMBIENT_RESOLVER",
    "EXEMPTION",
    "GENERATED_TREE_NAMES",
    "GUARDED_FACTORY",
    "HC_DESC",
    "HC_NAME",
    "SCAN_ROOTS",
    "UnguardedConnection",
    "hc_ambient_authority_connection_guard",
    "scan_for_unguarded_connections",
]

from yoke_project_checks._declare import (  # noqa: E402
    self_project_checks,
)

PROJECT_HEALTH_CHECKS = self_project_checks(
    (
        "ambient-authority-connection-guard",
        "Raw driver connections to the ambient Postgres authority must go "
        "through the guarded factory or declare local_authority_exempt()",
        hc_ambient_authority_connection_guard,
    ),
)
