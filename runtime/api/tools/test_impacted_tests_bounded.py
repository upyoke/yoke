"""Bounded selection and the fallback telemetry that explains widening.

Split from the main selection tests so each file stays within the
authored-file line limit. Two behaviors live here: declining to widen
when a later gate will run the full suite anyway, and recording *why* a
widening happened in a shape that can be grouped across many runs.
"""

from __future__ import annotations

from pathlib import Path

from yoke_core.tools import _impacted_unbounded_paths, impacted_tests, watch_pytest
from yoke_core.tools._impacted_contract_tests import (
    DIRECT_WORKFLOW_PREPARE_TESTS,
    DONE_TRANSITION_CLOSE_OUT_TESTS,
)
from yoke_core.tools.impacted_tests import Selection, build_import_index, select

from runtime.api.tools.test_impacted_tests import _tiny_repo, _with_floor, _write


def test_bounded_selection_declines_to_widen(tmp_path: Path) -> None:
    index = build_import_index(_tiny_repo(tmp_path))

    widened = select(["docs/lifecycle.md"], index)
    bounded = select(["docs/lifecycle.md"], index, bounded=True)

    assert widened.full_sweep is True
    assert bounded.full_sweep is False
    assert bounded.bounded_deferral is True
    assert "deferring full coverage to the final QA gate" in bounded.reason
    # Nothing was computable from a docs-only change, so the floor is all
    # that runs — never the anchors.
    assert bounded.pytest_paths() == _with_floor()


def test_bounded_selection_still_runs_the_computable_subset(tmp_path: Path) -> None:
    index = build_import_index(_tiny_repo(tmp_path))

    bounded = select(["docs/lifecycle.md", "runtime/api/leaf.py"], index, bounded=True)

    assert bounded.full_sweep is False
    assert bounded.fallback_rule == "unmapped_file_kind"
    # The Python half of the edit is still bounded by reachability, so its
    # reachable test runs rather than being lost with the unbounded half.
    assert "runtime/api/test_middle.py" in bounded.files


def test_bounded_test_tooling_change_does_not_reexpand_through_importers(
    tmp_path: Path,
) -> None:
    root = _tiny_repo(tmp_path)
    tooling = "packages/yoke-core/src/yoke_core/tools/watch_pytest.py"
    _write(root, tooling, "VALUE = 1\n")
    _write(
        root,
        "runtime/api/test_watch_consumer.py",
        "from yoke_core.tools import watch_pytest\n",
    )
    bounded = select([tooling], build_import_index(root), bounded=True)

    assert bounded.fallback_rule == "test_tooling_module"
    assert bounded.files == _with_floor()
    assert "runtime/api/test_watch_consumer.py" not in bounded.files


def test_bounded_near_total_reachability_defers_instead_of_expanding(
    tmp_path: Path,
) -> None:
    root = _tiny_repo(tmp_path)
    _write(root, "runtime/api/foundation.py", "VALUE = 1\n")
    for number in range(impacted_tests.MIN_EFFECTIVELY_FULL_FILE_UNIVERSE):
        _write(
            root,
            f"runtime/api/test_foundation_{number}.py",
            "from runtime.api import foundation\n",
        )

    index = build_import_index(root)
    plain = select(["runtime/api/foundation.py"], index)
    bounded = select(["runtime/api/foundation.py"], index, bounded=True)

    assert plain.full_sweep is True
    assert plain.fallback_rule == "effectively_full_selection"
    assert bounded.bounded_deferral is True
    assert bounded.files == _with_floor()


def test_bounded_trigger_defers_a_near_total_computable_remainder(
    tmp_path: Path,
) -> None:
    root = _tiny_repo(tmp_path)
    _write(root, "runtime/api/foundation.py", "VALUE = 1\n")
    for number in range(impacted_tests.MIN_EFFECTIVELY_FULL_FILE_UNIVERSE):
        _write(
            root,
            f"runtime/api/test_foundation_{number}.py",
            "from runtime.api import foundation\n",
        )

    bounded = select(
        ["docs/lifecycle.md", "runtime/api/foundation.py"],
        build_import_index(root),
        bounded=True,
    )

    assert bounded.fallback_rule == "unmapped_file_kind"
    assert bounded.bounded_deferral is True
    assert bounded.files == _with_floor()


def test_product_cli_change_keeps_boundary_contracts_when_selection_is_deferred(
    tmp_path,
) -> None:
    root = _tiny_repo(tmp_path)
    changed = "packages/yoke-cli/src/yoke_cli/commands/merge_item.py"
    tooling = "packages/yoke-core/src/yoke_core/tools/impacted_tests.py"
    _write(root, changed, "def merge_item(): pass\n")
    _write(root, tooling, "VALUE = 1\n")
    for test_path in impacted_tests.PRODUCT_CLI_BOUNDARY_TESTS:
        _write(root, test_path, "def test_product_boundary(): pass\n")

    selection = select([changed, tooling], build_import_index(root), bounded=True)

    assert selection.bounded_deferral is True
    assert set(impacted_tests.PRODUCT_CLI_BOUNDARY_TESTS) <= set(selection.files)


def test_service_client_projection_change_keeps_cli_contracts(tmp_path) -> None:
    root = _tiny_repo(tmp_path)
    changed = "packages/yoke-core/src/yoke_core/api/service_client_items_listing.py"
    for test_path in impacted_tests.PRODUCT_CLI_BOUNDARY_TESTS:
        _write(root, test_path, "def test_product_boundary(): pass\n")

    selection = select([changed], build_import_index(root), bounded=True)

    assert set(impacted_tests.PRODUCT_CLI_BOUNDARY_TESTS) <= set(selection.files)


def test_standalone_merge_change_keeps_close_out_contracts_when_deferred(
    tmp_path,
) -> None:
    root = _tiny_repo(tmp_path)
    changed = (
        "packages/yoke-core/src/yoke_core/domain/standalone_item_merge_recovery.py"
    )
    tooling = "packages/yoke-core/src/yoke_core/tools/impacted_tests.py"
    _write(root, changed, "def recover(): pass\n")
    _write(root, tooling, "VALUE = 1\n")
    for test_path in impacted_tests.STANDALONE_MERGE_CLOSE_OUT_TESTS:
        _write(root, test_path, "def test_close_out(): pass\n")

    selection = select([changed, tooling], build_import_index(root), bounded=True)

    assert selection.bounded_deferral is True
    assert set(impacted_tests.STANDALONE_MERGE_CLOSE_OUT_TESTS) <= set(selection.files)


def test_done_transition_change_keeps_cleanup_contracts(tmp_path) -> None:
    root = _tiny_repo(tmp_path)
    for changed in (
        "packages/yoke-core/src/yoke_core/engines/done_transition_runner.py",
        "packages/yoke-core/src/yoke_core/engines/done_transition_github_sync.py",
    ):
        _write(root, changed, "def run(): pass\n")
        for test_path in DONE_TRANSITION_CLOSE_OUT_TESTS:
            _write(root, test_path, "def test_close_out(): pass\n")

        selection = select([changed], build_import_index(root), bounded=True)

        assert set(DONE_TRANSITION_CLOSE_OUT_TESTS) <= set(selection.files)


def test_direct_workflow_prepare_change_keeps_receipt_consumers(tmp_path) -> None:
    root = _tiny_repo(tmp_path)
    changed = (
        "packages/yoke-core/src/yoke_core/domain/direct_workflow_worktree_preflight.py"
    )
    tooling = "packages/yoke-core/src/yoke_core/tools/_impacted_contract_tests.py"
    _write(root, changed, "def run(): pass\n")
    _write(root, tooling, "VALUE = 1\n")
    for test_path in DIRECT_WORKFLOW_PREPARE_TESTS:
        _write(root, test_path, "def test_receipt(): pass\n")

    selection = select([changed, tooling], build_import_index(root), bounded=True)

    assert set(DIRECT_WORKFLOW_PREPARE_TESTS) <= set(selection.files)


def test_bounded_selection_leaves_a_bounded_verdict_alone(tmp_path: Path) -> None:
    index = build_import_index(_tiny_repo(tmp_path))

    plain = select(["runtime/api/leaf.py"], index)
    bounded = select(["runtime/api/leaf.py"], index, bounded=True)

    assert bounded == plain
    assert bounded.bounded_deferral is False
    assert bounded.fallback_rule == ""


def test_each_widening_names_its_rule_and_the_paths_that_fired_it(
    tmp_path: Path,
) -> None:
    index = build_import_index(_tiny_repo(tmp_path))

    cases = {
        "runtime/api/conftest.py": "shared_test_fixture",
        "runtime/api/fixtures/pg_testdb.py": "shared_test_fixture",
        "packages/yoke-core/src/yoke_core/tools/gate_admission.py": (
            "test_tooling_module"
        ),
        "docs/lifecycle.md": "unmapped_file_kind",
        "scripts/one_off.py": "no_importable_module",
    }
    for changed, expected_rule in cases.items():
        selection = select([changed], index)
        assert selection.full_sweep is True, changed
        assert selection.fallback_rule == expected_rule, changed
        assert selection.trigger_paths == (changed,), changed
        assert selection.fallback_rule in impacted_tests.FALLBACK_RULES


def test_widening_reports_every_offending_path_not_just_the_first(
    tmp_path: Path,
) -> None:
    index = build_import_index(_tiny_repo(tmp_path))

    selection = select(["docs/a.md", "runtime/api/leaf.py", "docs/b.md"], index)

    assert selection.fallback_rule == "unmapped_file_kind"
    assert selection.trigger_paths == ("docs/a.md", "docs/b.md")


def test_telemetry_line_is_greppable_and_field_shaped() -> None:
    widened = Selection(
        full_sweep=True,
        reason="x",
        total_files=10,
        fallback_rule="shared_test_fixture",
        trigger_paths=("runtime/api/conftest.py",),
    )
    bounded = Selection(
        full_sweep=False,
        reason="y",
        files=("a/test_b.py",),
        total_files=10,
        fallback_rule="unmapped_file_kind",
        trigger_paths=("docs/a.md",),
        bounded_deferral=True,
    )
    plain = Selection(
        full_sweep=False, reason="z", files=("a/test_b.py",), total_files=10
    )

    assert widened.telemetry() == (
        "impacted-selection scope=full_sweep rule=shared_test_fixture "
        "triggers=runtime/api/conftest.py files=10 of 10 "
        "items=unknown of unknown"
    )
    assert bounded.telemetry() == (
        "impacted-selection scope=bounded_deferral rule=unmapped_file_kind "
        "triggers=docs/a.md files=1 of 10 items=unknown of unknown"
    )
    assert plain.telemetry() == (
        "impacted-selection scope=impacted rule=none triggers=none "
        "files=1 of 10 items=unknown of unknown"
    )


def test_item_counts_are_distinct_from_file_counts() -> None:
    selection = Selection(
        full_sweep=False,
        reason="x",
        files=("a/test_b.py",),
        total_files=10,
        selected_items=7,
        total_items=83,
    )

    assert selection.count_summary() == "files=1 of 10 items=7 of 83"


def test_watcher_footer_reports_collected_items_and_denominator() -> None:
    full = Selection(full_sweep=True, reason="x", total_files=10)
    partial = Selection(
        full_sweep=False, reason="x", files=("a/test_b.py",), total_files=10
    )

    assert watch_pytest._selection_footer(full, 83).endswith(
        "files=10 of 10 items=83 of 83"
    )
    assert watch_pytest._selection_footer(partial, 7).endswith(
        "files=1 of 10 items=7 of unknown"
    )


def test_fallback_rules_covers_every_rule_the_selector_can_emit() -> None:
    # The identifiers are the grouping key for captured telemetry, so the
    # published set and the rule table must not drift apart.
    from_table = {rule for rule, _paths, _why in _impacted_unbounded_paths.PATH_RULES}
    assert from_table <= set(impacted_tests.FALLBACK_RULES)
    assert len(impacted_tests.FALLBACK_RULES) == len(set(impacted_tests.FALLBACK_RULES))


def test_wrapper_prints_prose_reason_and_telemetry(capsys, monkeypatch) -> None:
    # Both land in the run's captures: prose for the agent reading along,
    # telemetry for grouping widenings across many runs.
    selection = Selection(
        full_sweep=True,
        reason="runtime/api/conftest.py is shared pytest infrastructure",
        fallback_rule="shared_test_fixture",
        trigger_paths=("runtime/api/conftest.py",),
    )
    monkeypatch.setattr(impacted_tests, "selection_for", lambda *a, **k: selection)

    selected = watch_pytest._impacted_selection("main")

    out = capsys.readouterr().out
    assert selected is selection
    assert "watch_pytest full sweep: " in out
    assert "watch_pytest impacted-selection scope=full_sweep" in out
    assert "rule=shared_test_fixture" in out


def test_wrapper_passes_bounded_through_to_selection(monkeypatch) -> None:
    seen: dict = {}

    def record(repo_root, base, *, bounded=False):
        seen["bounded"] = bounded
        return Selection(full_sweep=False, reason="ok", files=("a/test_b.py",))

    monkeypatch.setattr(impacted_tests, "selection_for", record)

    watch_pytest._impacted_selection("main", bounded=True)

    assert seen["bounded"] is True


def test_wrapper_rejects_bounded_without_impacted(capsys) -> None:
    exit_code = watch_pytest.main(["--bounded"])

    assert exit_code == 2
    assert "--bounded only applies with --impacted" in capsys.readouterr().err
