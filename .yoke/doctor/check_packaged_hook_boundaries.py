"""Doctor HCs for the installed hook engine's permanent code boundaries.

Product wheels never ship the checkout-only ``runtime`` namespace. Packaged
modules therefore cannot import harness code from that namespace, and hook
registries cannot name it indirectly. A local Postgres universe also treats
the installed engine entry as permanent authority: if that entry is missing,
the CLI adapter must report the defect and return nonzero.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence

from yoke_core.api.repo_root import find_repo_root
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from yoke_core.engines.doctor_tree_scan import GENERATED_TREE_NAMES, iter_tree_files
from yoke_project_checks._declare import self_project_checks


HC_SLUG = "packaged-hook-boundaries"
HC_NAME = "Packaged hook boundaries"
PACKAGE_SOURCE_ROOTS = (
    "packages/yoke-cli/src",
    "packages/yoke-contracts/src",
    "packages/yoke-core/src",
    "packages/yoke-harness/src",
)
HOOK_REGISTRY_ROOT = "packages/yoke-contracts/src/yoke_contracts/hook_runner"
LOCAL_HOOK_ADAPTER = (
    "packages/yoke-cli/src/yoke_cli/commands/adapters/hooks.py"
)
LOCAL_ENGINE_MODULE = "yoke_core.hooks.local_entry"
SOURCE_HOOK_PREFIX = "runtime.harness"


@dataclass(frozen=True)
class HookBoundaryFinding:
    """One permanent installed-hook boundary violation."""

    relpath: str
    line: int
    detail: str


def _project_root() -> Path:
    return find_repo_root(Path(__file__))


def _python_files(repo_root: Path, roots: Sequence[str]) -> Iterable[Path]:
    for root in roots:
        base = repo_root / root
        if not base.is_dir():
            continue
        yield from sorted(
            iter_tree_files(base, "*.py", prune_dir_names=GENERATED_TREE_NAMES)
        )


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imports(tree: ast.AST) -> Iterable[tuple[str, int]]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module, node.lineno


def scan_source_namespace_edges(
    repo_root: Path,
    *,
    package_roots: Sequence[str] = PACKAGE_SOURCE_ROOTS,
    registry_root: str = HOOK_REGISTRY_ROOT,
) -> List[HookBoundaryFinding]:
    """Find direct and registry-mediated edges to source-only hook modules."""
    findings: List[HookBoundaryFinding] = []
    for path in _python_files(repo_root, package_roots):
        relpath = path.relative_to(repo_root).as_posix()
        for imported, line in _imports(_parse(path)):
            if imported == SOURCE_HOOK_PREFIX or imported.startswith(
                SOURCE_HOOK_PREFIX + "."
            ):
                findings.append(HookBoundaryFinding(
                    relpath, line, f"imports source-only module {imported}",
                ))

    for path in _python_files(repo_root, (registry_root,)):
        relpath = path.relative_to(repo_root).as_posix()
        for node in ast.walk(_parse(path)):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node.value.startswith("runtime.")
            ):
                findings.append(HookBoundaryFinding(
                    relpath,
                    node.lineno,
                    f"registry names source-only module {node.value}",
                ))
    return findings


def _dynamic_import_target(node: ast.Call) -> str:
    if not node.args:
        return ""
    function = node.func
    name = (
        function.attr
        if isinstance(function, ast.Attribute)
        else function.id if isinstance(function, ast.Name) else ""
    )
    target = node.args[0]
    if (
        name == "import_module"
        and isinstance(target, ast.Constant)
        and isinstance(target.value, str)
    ):
        return target.value
    return ""


def _writes_stderr(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    function = node.func
    return (
        isinstance(function, ast.Attribute)
        and function.attr == "write"
        and isinstance(function.value, ast.Attribute)
        and function.value.attr == "stderr"
    )


def _handler_failures(handler: ast.ExceptHandler) -> List[str]:
    nodes = tuple(ast.walk(handler))
    raises = any(isinstance(node, ast.Raise) for node in nodes)
    writes_stderr = any(_writes_stderr(node) for node in nodes)
    returns = [node for node in nodes if isinstance(node, ast.Return)]
    nonzero_returns = [
        node
        for node in returns
        if isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, int)
        and node.value.value != 0
    ]
    failures: List[str] = []
    if not writes_stderr and not raises:
        failures.append("missing stderr report or raise")
    if not raises and not nonzero_returns:
        failures.append("missing nonzero return or raise")
    if len(nonzero_returns) != len(returns):
        failures.append("contains a zero, empty, or non-integer return")
    return failures


def scan_local_engine_fail_loud(
    repo_root: Path,
    *,
    adapter: str = LOCAL_HOOK_ADAPTER,
) -> List[HookBoundaryFinding]:
    """Find a missing or silently permissive local-engine import handler."""
    path = repo_root / adapter
    tree = _parse(path)
    matching: List[ast.Try] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        targets = {
            _dynamic_import_target(child)
            for statement in node.body
            for child in ast.walk(statement)
            if isinstance(child, ast.Call)
        }
        if LOCAL_ENGINE_MODULE in targets:
            matching.append(node)
    if len(matching) != 1:
        return [HookBoundaryFinding(
            adapter,
            1,
            f"expected one guarded import of {LOCAL_ENGINE_MODULE}; "
            f"found {len(matching)}",
        )]

    findings: List[HookBoundaryFinding] = []
    guarded_import = matching[0]
    if not guarded_import.handlers:
        findings.append(HookBoundaryFinding(
            adapter, guarded_import.lineno, "local engine import is unguarded",
        ))
    for handler in guarded_import.handlers:
        for failure in _handler_failures(handler):
            findings.append(HookBoundaryFinding(
                adapter, handler.lineno, failure,
            ))
    return findings


def scan_packaged_hook_boundaries(repo_root: Path) -> List[HookBoundaryFinding]:
    """Return every installed-hook architecture or fail-loud violation."""
    return [
        *scan_source_namespace_edges(repo_root),
        *scan_local_engine_fail_loud(repo_root),
    ]


def hc_packaged_hook_boundaries(
    conn,
    args: DoctorArgs,
    rec: RecordCollector,
) -> None:
    """Require wheel-safe hook edges and a loud permanent-import failure."""
    findings = scan_packaged_hook_boundaries(_project_root())
    if not findings:
        rec.record(
            f"HC-{HC_SLUG}",
            HC_NAME,
            "PASS",
            "Hook registries and packaged modules name only shipped code, and "
            "a missing local engine entry reports the defect and returns nonzero.",
        )
        return
    detail = "\n".join(
        f"- `{finding.relpath}:{finding.line}` {finding.detail}"
        for finding in findings
    )
    rec.record(f"HC-{HC_SLUG}", HC_NAME, "FAIL", detail)


PROJECT_HEALTH_CHECKS = self_project_checks(
    (HC_SLUG, HC_NAME, hc_packaged_hook_boundaries),
)


__all__ = [
    "HookBoundaryFinding",
    "PROJECT_HEALTH_CHECKS",
    "hc_packaged_hook_boundaries",
    "scan_local_engine_fail_loud",
    "scan_packaged_hook_boundaries",
    "scan_source_namespace_edges",
]
