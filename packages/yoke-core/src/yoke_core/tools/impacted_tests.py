"""Select the tests a change could plausibly break, from import reachability.

A full sweep runs every test in the repository regardless of what changed,
so a one-file edit costs the same as a schema rewrite — and when several
checkouts verify at once, that fixed cost is what makes everyone queue.
Most changes, though, can only affect a small part of the suite: a module
is reachable from some tests and not from others.

This builds the reverse of the import graph — for each module, which files
import it — and walks it from the changed files outward. Every test file in
that closure is selected; everything else provably cannot import the change.

**This is an accelerator for iteration, not a merge gate.** Static imports
do not capture every way a test can depend on code:

- a test that shells out to a CLI exercises modules it never imports;
- ``from package import name`` records ``package.name`` but attribute
  access after ``from package import subpackage`` is not resolved;
- dynamic imports by computed name are invisible.

So selection is opt-in, and anything that could ripple everywhere falls
back to the full sweep by construction (see :data:`FULL_SWEEP_TRIGGERS`):
non-Python files, shared fixtures, conftest modules, and the test tooling
itself. The full sweep still runs before merge — a missed edge costs a
late failure, never a silent one.
"""

from __future__ import annotations

import ast
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

#: Directories pytest is pointed at for a full sweep.
TEST_ANCHORS = ("runtime/api/", "runtime/harness/", "tests/")

#: A change matching any of these can reach tests the import graph does not
#: model, so it forces the full sweep instead of a selection.
FULL_SWEEP_TRIGGERS = (
    "conftest.py",
    "runtime/api/fixtures/",
    "packages/yoke-core/src/yoke_core/tools/impacted_tests.py",
    "packages/yoke-core/src/yoke_core/tools/_pytest_parallel.py",
    "packages/yoke-core/src/yoke_core/tools/run_tests.py",
    "packages/yoke-core/src/yoke_core/tools/gate_admission.py",
    "packages/yoke-core/src/yoke_core/tools/pg_testcluster.py",
)

_PACKAGE_SOURCE_MARKER = "/src/"
_SKIP_DIRECTORIES = frozenset(
    {".git", ".venv", "node_modules", "__pycache__", ".worktrees", "build"}
)


@dataclass(frozen=True)
class Selection:
    """What to run, and why."""

    full_sweep: bool
    reason: str
    tests: tuple[str, ...] = ()

    def pytest_paths(self) -> tuple[str, ...]:
        return TEST_ANCHORS if self.full_sweep else self.tests


def changed_paths(repo_root: Path, base: str) -> tuple[str, ...]:
    """Repo-relative paths differing from *base*, including uncommitted work."""
    seen: list[str] = []
    for args in (
        ["diff", "--name-only", f"{base}...HEAD"],
        ["diff", "--name-only", "HEAD"],
        ["ls-files", "--others", "--exclude-standard"],
    ):
        result = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            continue
        for line in result.stdout.splitlines():
            line = line.strip()
            if line and line not in seen:
                seen.append(line)
    return tuple(seen)


def is_test_file(rel_path: str) -> bool:
    name = rel_path.rsplit("/", 1)[-1]
    return name.startswith("test_") and name.endswith(".py")


def module_name_for(rel_path: str) -> "str | None":
    """Dotted module name for a repo-relative source path, if it is one."""
    if not rel_path.endswith(".py"):
        return None
    trimmed = rel_path[: -len(".py")]
    marker_at = trimmed.find(_PACKAGE_SOURCE_MARKER)
    if marker_at != -1:
        trimmed = trimmed[marker_at + len(_PACKAGE_SOURCE_MARKER) :]
    if trimmed.endswith("/__init__"):
        trimmed = trimmed[: -len("/__init__")]
    return trimmed.replace("/", ".")


def _iter_source_files(repo_root: Path) -> Iterable[Path]:
    for path in repo_root.rglob("*.py"):
        if any(part in _SKIP_DIRECTORIES for part in path.parts):
            continue
        if ".egg-info" in str(path):
            continue
        yield path


def _imported_modules(tree: ast.AST, own_module: "str | None") -> set[str]:
    """Modules referenced by *tree*, including resolved relative imports."""
    package = own_module.rsplit(".", 1)[0] if own_module and "." in own_module else ""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                ancestor = package
                for _ in range(node.level - 1):
                    ancestor = ancestor.rsplit(".", 1)[0] if "." in ancestor else ""
                base = f"{ancestor}.{base}" if base else ancestor
            if not base:
                continue
            found.add(base)
            # ``from pkg import name`` may be importing a module or a symbol;
            # record both readings and let the index decide which exists.
            for alias in node.names:
                found.add(f"{base}.{alias.name}")
    return found


@dataclass(frozen=True)
class ImportIndex:
    """Reverse import edges plus the module name of every source file."""

    importers: dict[str, set[str]]
    module_of: dict[str, str]


def build_import_index(repo_root: Path) -> ImportIndex:
    importers: dict[str, set[str]] = {}
    module_of: dict[str, str] = {}
    for path in _iter_source_files(repo_root):
        rel = path.relative_to(repo_root).as_posix()
        module = module_name_for(rel)
        if module:
            module_of[rel] = module
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except (SyntaxError, ValueError, OSError):
            continue
        for referenced in _imported_modules(tree, module):
            importers.setdefault(referenced, set()).add(rel)
    return ImportIndex(importers=importers, module_of=module_of)


def _full_sweep_trigger(changed: Sequence[str]) -> "str | None":
    for rel in changed:
        if not rel.endswith(".py"):
            return f"{rel} is not a Python module; import reachability cannot model it"
        for trigger in FULL_SWEEP_TRIGGERS:
            if rel == trigger or rel.endswith(f"/{trigger}") or rel.startswith(trigger):
                return f"{rel} can affect any test"
    return None


def select(changed: Sequence[str], index: ImportIndex) -> Selection:
    """Tests reachable from *changed*, or a reasoned full sweep."""
    if not changed:
        return Selection(full_sweep=False, reason="no changes", tests=())
    trigger = _full_sweep_trigger(changed)
    if trigger:
        return Selection(full_sweep=True, reason=trigger)

    reached: set[str] = set(changed)
    frontier = [
        module for rel in changed if (module := index.module_of.get(rel)) is not None
    ]
    if not frontier:
        return Selection(
            full_sweep=True,
            reason="changed files resolve to no importable module",
        )
    seen_modules = set(frontier)
    while frontier:
        module = frontier.pop()
        for importer in index.importers.get(module, ()):
            if importer in reached:
                continue
            reached.add(importer)
            importer_module = index.module_of.get(importer)
            if importer_module and importer_module not in seen_modules:
                seen_modules.add(importer_module)
                frontier.append(importer_module)

    tests = tuple(sorted(rel for rel in reached if is_test_file(rel)))
    if not tests:
        return Selection(
            full_sweep=False,
            reason="no test imports the changed modules",
            tests=(),
        )
    return Selection(
        full_sweep=False,
        reason=f"{len(tests)} test file(s) import the changed modules",
        tests=tests,
    )


def selection_for(repo_root: Path, base: str) -> Selection:
    changed = changed_paths(repo_root, base)
    return select(changed, build_import_index(repo_root))


def main(argv: "Sequence[str] | None" = None) -> int:
    import argparse
    import sys

    from yoke_core.tools import _source_pythonpath

    parser = argparse.ArgumentParser(
        prog="impacted_tests",
        description=(
            "Print the test files a change could reach, or the full-sweep "
            "anchors when reachability cannot bound it."
        ),
    )
    parser.add_argument("--base", default="main", help="Base ref (default: main)")
    parser.add_argument(
        "--explain",
        action="store_true",
        help="Also print the reason on stderr.",
    )
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))

    repo_root = _source_pythonpath.repo_root(Path.cwd())
    selection = selection_for(repo_root, args.base)
    if args.explain:
        scope = "full sweep" if selection.full_sweep else "selected"
        print(f"{scope}: {selection.reason}", file=sys.stderr)
    for path in selection.pytest_paths():
        print(path)
    return 0


if __name__ == "__main__":  # pragma: no cover — exercised via subprocess
    raise SystemExit(main())
