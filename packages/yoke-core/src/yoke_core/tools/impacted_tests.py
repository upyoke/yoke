"""Select tests by import reachability with bounded and full-sweep fallbacks."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Sequence

from yoke_core.tools._impacted_changed_paths import DEFAULT_BASE_REF, changed_paths
from yoke_core.tools._impacted_contract_tests import (
    AGENT_SKILL_CONTRACT_TESTS,
    ALWAYS_RUN_TESTS,
    ITEM_WORKTREE_SCHEMA_TESTS,
    PRODUCT_CLI_BOUNDARY_TESTS,
    REPO_CLEANLINESS_TESTS,
    SCHEMA_CONVERGE_CONTRACT_TESTS,
    STANDALONE_MERGE_CLOSE_OUT_TESTS,
    contract_selection_for,
)
from yoke_core.tools._impacted_contract_tests_session_control import (
    session_control_contract_selection,
)
from yoke_core.tools._impacted_import_index import (
    ImportIndex,
    TEST_ANCHORS,
    bounded_importer_tests,
    build_import_index,
    direct_changed_tests,
    is_test_file,
    module_name_for,
    reachable_tests,
)
from yoke_core.tools._impacted_selection import (
    MIN_EFFECTIVELY_FULL_FILE_UNIVERSE,
    Selection,
    is_effectively_full,
    remainder_paths_for_bounded_reachability,
)

from yoke_core.tools._impacted_unbounded_paths import (
    FALLBACK_RULES,
    FULL_SWEEP_TRIGGERS,
    NO_MODULE_REASON,
    SHARED_TEST_FIXTURE_PATHS,
    TEST_TOOLING_PATHS,
    unbounded_trigger,
)


def _widened(changed: Sequence[str], index: ImportIndex) -> Selection:
    """Tests reachable from *changed*, widening when nothing bounds it."""
    if not changed:
        return Selection(full_sweep=False, reason="no changes", files=())

    trigger = unbounded_trigger(changed)
    if trigger is not None:
        rule, paths, why = trigger
        return Selection(
            full_sweep=True,
            reason=f"{', '.join(paths)} {why}",
            fallback_rule=rule,
            trigger_paths=paths,
        )

    reached_tests = reachable_tests(changed, index)
    if reached_tests is None:
        return Selection(
            full_sweep=True,
            reason=NO_MODULE_REASON,
            fallback_rule="no_importable_module",
            trigger_paths=tuple(changed),
        )

    if not reached_tests:
        return Selection(
            full_sweep=False,
            reason=(
                "no test reaches the changed modules; "
                "running the always-run contract tests"
            ),
            files=(),
        )
    return Selection(
        full_sweep=False,
        reason=(
            f"{len(reached_tests)} test file(s) reach the changed modules, "
            "plus the always-run contract tests"
        ),
        files=tuple(sorted(reached_tests)),
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
    total_files = sum(is_test_file(path) for path in index.module_of)
    contracts = contract_selection_for(changed)
    session_contracts = session_control_contract_selection(changed)
    contracts = replace(
        contracts,
        tests=contracts.tests | session_contracts.tests,
        widening_triggers=(
            contracts.widening_triggers + session_contracts.widening_triggers
        ),
    )
    applicable_contracts = contracts.tests.intersection(index.module_of)
    contracts = replace(
        contracts,
        tests=frozenset(applicable_contracts),
        widening_triggers=(contracts.widening_triggers if applicable_contracts else ()),
    )
    direct = direct_changed_tests(changed, index)
    selection = replace(_widened(changed, index), total_files=total_files)
    if not selection.full_sweep:
        selection = replace(
            selection,
            files=tuple(sorted(set(selection.files) | contracts.tests | direct)),
            widening_triggers=contracts.widening_triggers,
        )
    selected_files = sum(path in index.module_of for path in selection.files)
    if not selection.full_sweep and is_effectively_full(selected_files, total_files):
        individually_broad = tuple(
            path
            for path in changed
            if is_effectively_full(
                len(reachable_tests((path,), index) or ()), total_files
            )
        )
        selection = Selection(
            full_sweep=True,
            reason=f"reachability selected {selected_files} of {total_files} test files",
            total_files=total_files,
            fallback_rule="effectively_full_selection",
            trigger_paths=individually_broad or tuple(changed),
        )
    if not (bounded and selection.full_sweep):
        return selection
    trigger_paths = set(selection.trigger_paths)
    bounded_changed = [path for path in changed if path not in trigger_paths]
    reached = (
        reachable_tests(
            remainder_paths_for_bounded_reachability(
                bounded_changed,
                total_files=total_files,
                individually_reached=lambda path: len(
                    reachable_tests((path,), index) or ()
                ),
            ),
            index,
        )
        or set()
    )
    reached_count = len(reached)
    importer_sources = (
        changed
        if selection.fallback_rule == "effectively_full_selection"
        else bounded_changed
    )
    bounded_importers = bounded_importer_tests(
        importer_sources,
        index,
        total_files=total_files,
    )
    if is_effectively_full(len(bounded_importers), total_files):
        bounded_importers = frozenset()
    if is_effectively_full(reached_count, total_files):
        reached = set()
        subset_note = (
            f"; computable subset selected {reached_count} of {total_files} "
            "test files and was also deferred"
        )
    else:
        subset_note = ""
    return Selection(
        full_sweep=False,
        reason=(
            f"selection unbounded ({selection.fallback_rule}: "
            f"{', '.join(selection.trigger_paths)}) — deferring full "
            f"coverage to the final QA gate{subset_note}"
        ),
        files=tuple(sorted(reached | contracts.tests | direct | bounded_importers)),
        total_files=total_files,
        fallback_rule=selection.fallback_rule,
        trigger_paths=selection.trigger_paths,
        widening_triggers=contracts.widening_triggers,
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
    parser.add_argument(
        "--base",
        default=DEFAULT_BASE_REF,
        help=f"Base ref (default: {DEFAULT_BASE_REF})",
    )
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
        print(
            f"{scope}: {selection.reason}; {selection.count_summary()}",
            file=sys.stderr,
        )
        print(selection.telemetry(), file=sys.stderr)
    for path in selection.pytest_paths():
        print(path)
    return 0


__all__ = [
    "AGENT_SKILL_CONTRACT_TESTS",
    "ALWAYS_RUN_TESTS",
    "FALLBACK_RULES",
    "FULL_SWEEP_TRIGGERS",
    "ImportIndex",
    "ITEM_WORKTREE_SCHEMA_TESTS",
    "MIN_EFFECTIVELY_FULL_FILE_UNIVERSE",
    "PRODUCT_CLI_BOUNDARY_TESTS",
    "REPO_CLEANLINESS_TESTS",
    "SCHEMA_CONVERGE_CONTRACT_TESTS",
    "STANDALONE_MERGE_CLOSE_OUT_TESTS",
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
