"""Select the tests a change could plausibly break, from import reachability.

A full sweep costs the same for a one-file edit as for a schema rewrite,
and when several checkouts verify at once that fixed cost is what makes
everyone queue. Most changes can only affect part of the suite. This
walks the reverse import graph (built by
:mod:`yoke_core.tools._impacted_import_index`) outward from the changed
files; everything outside that closure provably cannot import the change.
A small :data:`ALWAYS_RUN_TESTS` floor runs regardless, so a wiring break
the closure missed still fails locally.

**An accelerator for iteration, not a merge gate.** A change that could
ripple everywhere is *unbounded*, and the caller chooses what that means:
plain selection answers with the full-sweep anchors (correct standalone,
with no later gate behind it), while bounded selection refuses to widen —
it runs the subset it can still compute and says why coverage is partial.
Bounded is the iteration shape: the final QA case run is the one full
execution, so widening mid-iteration burns a suite about to run anyway.

Every unbounded verdict names its :data:`FALLBACK_RULES` rule and the
exact files that fired it, so a sweep of run captures shows whether
widening is legitimate core churn or an unmodelled file kind. CI runs the
full sweep on every pull request and merge, so a missed edge costs a late
failure rather than a silent one — and that failure is a selector defect:
model the missed edge here, with a regression test, in the same fix.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from yoke_core.tools._impacted_import_index import (
    ImportIndex,
    build_import_index,
    is_test_file,
    module_name_for,
)

#: Directories pytest is pointed at for a full sweep.
TEST_ANCHORS = ("runtime/api/", "runtime/harness/", "tests/")

#: Shared pytest infrastructure: reachable from every test by construction
#: rather than by import, so a change here is unbounded.
SHARED_TEST_FIXTURE_PATHS = (
    "conftest.py",
    "runtime/api/fixtures/",
)

#: The selection and test-run machinery itself. A change here can alter
#: what any other run selects or how it executes.
TEST_TOOLING_PATHS = (
    "packages/yoke-core/src/yoke_core/tools/impacted_tests.py",
    "packages/yoke-core/src/yoke_core/tools/_impacted_import_index.py",
    "packages/yoke-core/src/yoke_core/tools/_pytest_parallel.py",
    "packages/yoke-core/src/yoke_core/tools/run_tests.py",
    "packages/yoke-core/src/yoke_core/tools/gate_admission.py",
    "packages/yoke-core/src/yoke_core/tools/pg_testcluster.py",
)

#: A change matching any of these can reach tests the import graph does not
#: model, so it cannot be bounded by reachability.
FULL_SWEEP_TRIGGERS = SHARED_TEST_FIXTURE_PATHS + TEST_TOOLING_PATHS

#: Path-matched unbounded rules: identifier, the paths it covers, and the
#: prose half of the verdict. One table so the agent-facing reason and the
#: telemetry grouping key can never drift apart.
_PATH_RULES = (
    (
        "shared_test_fixture",
        SHARED_TEST_FIXTURE_PATHS,
        "is shared pytest infrastructure and can affect any test",
    ),
    (
        "test_tooling_module",
        TEST_TOOLING_PATHS,
        "selects or runs the suite itself and can affect any test",
    ),
)

_UNMAPPED_REASON = "is not a Python module; import reachability cannot model it"
_NO_MODULE_REASON = "changed files resolve to no importable module"

#: Why a selection could not be bounded. Stable identifiers: they group
#: fallback telemetry across runs, so a rename breaks comparison with
#: everything already captured.
FALLBACK_RULES = tuple(rule for rule, _paths, _why in _PATH_RULES) + (
    "unmapped_file_kind",
    "no_importable_module",
)

#: Fast cross-cutting contract tests appended to every impacted selection.
#: They exercise CLI registry, operation inventory, and adapter parity
#: end-to-end — where a break hides from reachability yet fails the sweep.
ALWAYS_RUN_TESTS = (
    "runtime/api/cli/test_adapter_inventory_usage_contract.py",
    "runtime/api/cli/test_yoke_operation_inventory.py",
    "runtime/api/test_service_client_structured_api_adapter.py",
)


@dataclass(frozen=True)
class Selection:
    """What to run, and why."""

    full_sweep: bool
    reason: str
    tests: tuple[str, ...] = ()
    #: Which :data:`FALLBACK_RULES` rule made this selection unbounded.
    #: Empty when reachability bounded the change.
    fallback_rule: str = ""
    #: The exact changed files that fired ``fallback_rule``.
    trigger_paths: tuple[str, ...] = ()
    #: True when a bounded caller declined to widen an unbounded verdict.
    bounded_deferral: bool = False

    def pytest_paths(self) -> tuple[str, ...]:
        return TEST_ANCHORS if self.full_sweep else self.tests

    def telemetry(self) -> str:
        """One greppable ``key=value`` line describing this selection.

        Written to the run's captures. Answering "was that widening
        legitimate?" across many runs needs the rule and the offending
        paths as fields, not a prose reason to classify by hand.
        """
        if self.full_sweep:
            scope = "full_sweep"
        elif self.bounded_deferral:
            scope = "bounded_deferral"
        else:
            scope = "impacted"
        fields = [f"scope={scope}", f"rule={self.fallback_rule or 'none'}"]
        fields.append(f"triggers={','.join(self.trigger_paths) or 'none'}")
        fields.append(f"tests={len(self.tests)}")
        return "impacted-selection " + " ".join(fields)


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


def _matches(rel: str, prefixes: Sequence[str]) -> bool:
    return any(
        rel == prefix or rel.endswith(f"/{prefix}") or rel.startswith(prefix)
        for prefix in prefixes
    )


def _unbounded_trigger(
    changed: Sequence[str],
) -> "tuple[str, tuple[str, ...], str] | None":
    """Rule, every path firing it, and why — or None when bounded.

    All offending paths, not the first: the telemetry question is whether
    one genuinely central file widened the run or the whole edit is
    invisible to reachability.
    """
    for rule, prefixes, why in _PATH_RULES:
        hits = tuple(rel for rel in changed if _matches(rel, prefixes))
        if hits:
            return rule, hits, why
    unmapped = tuple(rel for rel in changed if not rel.endswith(".py"))
    if unmapped:
        return "unmapped_file_kind", unmapped, _UNMAPPED_REASON
    return None


def _reachable_tests(changed: Sequence[str], index: ImportIndex) -> "set[str] | None":
    """Test files reachable from *changed*, or None when nothing maps."""
    reached: set[str] = set(changed)
    frontier = [
        module for rel in changed if (module := index.module_of.get(rel)) is not None
    ]
    if not frontier:
        return None
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
    return {rel for rel in reached if is_test_file(rel)}


def _widened(changed: Sequence[str], index: ImportIndex) -> Selection:
    """Tests reachable from *changed*, widening when nothing bounds it."""
    if not changed:
        return Selection(full_sweep=False, reason="no changes", tests=())

    trigger = _unbounded_trigger(changed)
    if trigger is not None:
        rule, paths, why = trigger
        return Selection(
            full_sweep=True,
            reason=f"{', '.join(paths)} {why}",
            fallback_rule=rule,
            trigger_paths=paths,
        )

    reached_tests = _reachable_tests(changed, index)
    if reached_tests is None:
        return Selection(
            full_sweep=True,
            reason=_NO_MODULE_REASON,
            fallback_rule="no_importable_module",
            trigger_paths=tuple(changed),
        )

    tests = tuple(sorted(reached_tests | set(ALWAYS_RUN_TESTS)))
    if not reached_tests:
        return Selection(
            full_sweep=False,
            reason=(
                "no test reaches the changed modules; "
                "running the always-run contract tests"
            ),
            tests=tests,
        )
    return Selection(
        full_sweep=False,
        reason=(
            f"{len(reached_tests)} test file(s) reach the changed modules, "
            "plus the always-run contract tests"
        ),
        tests=tests,
    )


def select(
    changed: Sequence[str],
    index: ImportIndex,
    *,
    bounded: bool = False,
) -> Selection:
    """Tests reachable from *changed*, or a reasoned unbounded verdict.

    ``bounded=True`` declines the widening: the caller gets the subset
    reachability could still compute plus the reason its coverage is
    partial, rather than a full sweep the final gate will run anyway.
    """
    selection = _widened(changed, index)
    if not (bounded and selection.full_sweep):
        return selection
    reached = _reachable_tests(changed, index) or set()
    return Selection(
        full_sweep=False,
        reason=(
            f"selection unbounded ({selection.fallback_rule}: "
            f"{', '.join(selection.trigger_paths)}) — deferring full "
            "coverage to the final QA gate"
        ),
        tests=tuple(sorted(reached | set(ALWAYS_RUN_TESTS))),
        fallback_rule=selection.fallback_rule,
        trigger_paths=selection.trigger_paths,
        bounded_deferral=True,
    )


def selection_for(repo_root: Path, base: str, *, bounded: bool = False) -> Selection:
    changed = changed_paths(repo_root, base)
    return select(changed, build_import_index(repo_root), bounded=bounded)


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
        "--bounded",
        action="store_true",
        help="Never widen to the full sweep. Prints the computable subset "
        "and reports the unbounded reason on stderr instead.",
    )
    parser.add_argument(
        "--explain",
        action="store_true",
        help="Also print the reason and fallback telemetry on stderr.",
    )
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))

    repo_root = _source_pythonpath.repo_root(Path.cwd())
    selection = selection_for(repo_root, args.base, bounded=args.bounded)
    if args.explain:
        scope = "full sweep" if selection.full_sweep else "selected"
        print(f"{scope}: {selection.reason}", file=sys.stderr)
        print(selection.telemetry(), file=sys.stderr)
    for path in selection.pytest_paths():
        print(path)
    return 0


__all__ = [
    "ALWAYS_RUN_TESTS",
    "FALLBACK_RULES",
    "FULL_SWEEP_TRIGGERS",
    "ImportIndex",
    "Selection",
    "SHARED_TEST_FIXTURE_PATHS",
    "TEST_ANCHORS",
    "TEST_TOOLING_PATHS",
    "build_import_index",
    "changed_paths",
    "is_test_file",
    "main",
    "module_name_for",
    "select",
    "selection_for",
]


if __name__ == "__main__":  # pragma: no cover — exercised via subprocess
    raise SystemExit(main())
