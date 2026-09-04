"""Changed paths that reachability cannot bound, and why.

Split from :mod:`yoke_core.tools.impacted_tests` to keep that module under
the authored-file line cap. The tables here answer one question for a
changed path: can the import graph say which tests it reaches? Shared
pytest infrastructure reaches every test by construction, and the
selection machinery itself can change what any run selects or how it
executes, so a change to either is unbounded by definition.
"""

from __future__ import annotations

from typing import Sequence

#: Shared pytest infrastructure: reachable from every test by construction
#: rather than by import, so a change here is unbounded.
SHARED_TEST_FIXTURE_PATHS = (
    "conftest.py",
    "runtime/api/fixtures/",
)

#: The selection and test-run machinery itself. A change here can alter
#: what any other run selects or how it executes.
TEST_TOOLING_PATHS = (
    "packages/yoke-core/src/yoke_core/tools/_impacted_changed_paths.py",
    "packages/yoke-core/src/yoke_core/tools/_impacted_contract_tests.py",
    "packages/yoke-core/src/yoke_core/tools/"
    "_impacted_contract_tests_session_control.py",
    "packages/yoke-core/src/yoke_core/tools/impacted_tests.py",
    "packages/yoke-core/src/yoke_core/tools/_impacted_selection.py",
    "packages/yoke-core/src/yoke_core/tools/_impacted_unbounded_paths.py",
    "packages/yoke-core/src/yoke_core/tools/watch_pytest.py",
    "packages/yoke-core/src/yoke_core/tools/watch_pytest_project_python.py",
    "packages/yoke-core/src/yoke_core/tools/watch_pytest_remote.py",
    "packages/yoke-core/src/yoke_core/tools/_watch_pytest_args.py",
    "packages/yoke-core/src/yoke_core/tools/_watch_pytest_classify.py",
    "packages/yoke-core/src/yoke_core/tools/_watch_runner.py",
    "packages/yoke-core/src/yoke_core/tools/_impacted_import_index.py",
    "packages/yoke-core/src/yoke_core/tools/_pytest_parallel.py",
    "packages/yoke-core/src/yoke_core/tools/pytest_remote_selection.py",
    "packages/yoke-core/src/yoke_core/tools/pytest_remote_selection_run.py",
    "packages/yoke-core/src/yoke_core/tools/pytest_worker_budget.py",
    "packages/yoke-core/src/yoke_core/tools/ci_selection_run.py",
    "packages/yoke-core/src/yoke_core/tools/run_tests.py",
    "packages/yoke-core/src/yoke_core/tools/_run_tests_args.py",
    "packages/yoke-core/src/yoke_core/tools/gate_admission.py",
    "packages/yoke-core/src/yoke_core/tools/pg_testcluster.py",
)

#: A change matching any of these can reach tests the import graph does not
#: model, so it cannot be bounded by reachability.
FULL_SWEEP_TRIGGERS = SHARED_TEST_FIXTURE_PATHS + TEST_TOOLING_PATHS

#: Path-matched unbounded rules: identifier, the paths it covers, and the
#: prose half of the verdict. One table so the agent-facing reason and the
#: telemetry grouping key can never drift apart.
PATH_RULES = (
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

UNMAPPED_REASON = "is not a Python module; import reachability cannot model it"
NO_MODULE_REASON = "changed files resolve to no importable module"

#: Why a selection could not be bounded. Stable identifiers: they group
#: fallback telemetry across runs, so a rename breaks comparison with
#: everything already captured.
FALLBACK_RULES = tuple(rule for rule, _paths, _why in PATH_RULES) + (
    "unmapped_file_kind",
    "no_importable_module",
    "effectively_full_selection",
)


def matches(rel: str, prefixes: Sequence[str]) -> bool:
    return any(
        rel == prefix or rel.endswith(f"/{prefix}") or rel.startswith(prefix)
        for prefix in prefixes
    )


def unbounded_trigger(
    changed: Sequence[str],
) -> "tuple[str, tuple[str, ...], str] | None":
    """Rule, every path firing it, and why — or None when bounded.

    All offending paths, not the first: the telemetry question is whether
    one genuinely central file widened the run or the whole edit is
    invisible to reachability.
    """
    for rule, prefixes, why in PATH_RULES:
        hits = tuple(rel for rel in changed if matches(rel, prefixes))
        if hits:
            return rule, hits, why
    unmapped = tuple(rel for rel in changed if not rel.endswith(".py"))
    if unmapped:
        return "unmapped_file_kind", unmapped, UNMAPPED_REASON
    return None


__all__ = [
    "FALLBACK_RULES",
    "FULL_SWEEP_TRIGGERS",
    "NO_MODULE_REASON",
    "PATH_RULES",
    "SHARED_TEST_FIXTURE_PATHS",
    "TEST_TOOLING_PATHS",
    "UNMAPPED_REASON",
    "matches",
    "unbounded_trigger",
]
