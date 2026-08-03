"""Bounded selection and the fallback telemetry that explains widening.

Split from the main selection tests so each file stays within the
authored-file line limit. Two behaviors live here: declining to widen
when a later gate will run the full suite anyway, and recording *why* a
widening happened in a shape that can be grouped across many runs.
"""

from __future__ import annotations

from pathlib import Path

from yoke_core.tools import impacted_tests, watch_pytest
from yoke_core.tools.impacted_tests import Selection, build_import_index, select

from runtime.api.tools.test_impacted_tests import _tiny_repo, _with_floor


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

    bounded = select(
        ["docs/lifecycle.md", "runtime/api/leaf.py"], index, bounded=True
    )

    assert bounded.full_sweep is False
    assert bounded.fallback_rule == "unmapped_file_kind"
    # The Python half of the edit is still bounded by reachability, so its
    # reachable test runs rather than being lost with the unbounded half.
    assert "runtime/api/test_middle.py" in bounded.tests


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
        fallback_rule="shared_test_fixture",
        trigger_paths=("runtime/api/conftest.py",),
    )
    bounded = Selection(
        full_sweep=False,
        reason="y",
        tests=("a/test_b.py",),
        fallback_rule="unmapped_file_kind",
        trigger_paths=("docs/a.md",),
        bounded_deferral=True,
    )
    plain = Selection(full_sweep=False, reason="z", tests=("a/test_b.py",))

    assert widened.telemetry() == (
        "impacted-selection scope=full_sweep rule=shared_test_fixture "
        "triggers=runtime/api/conftest.py tests=0"
    )
    assert bounded.telemetry() == (
        "impacted-selection scope=bounded_deferral rule=unmapped_file_kind "
        "triggers=docs/a.md tests=1"
    )
    assert plain.telemetry() == (
        "impacted-selection scope=impacted rule=none triggers=none tests=1"
    )


def test_fallback_rules_covers_every_rule_the_selector_can_emit() -> None:
    # The identifiers are the grouping key for captured telemetry, so the
    # published set and the rule table must not drift apart.
    from_table = {rule for rule, _paths, _why in impacted_tests._PATH_RULES}
    assert from_table <= set(impacted_tests.FALLBACK_RULES)
    assert len(impacted_tests.FALLBACK_RULES) == len(
        set(impacted_tests.FALLBACK_RULES)
    )


def test_wrapper_prints_prose_reason_and_telemetry(capsys, monkeypatch) -> None:
    # Both land in the run's captures: prose for the agent reading along,
    # telemetry for grouping widenings across many runs.
    selection = Selection(
        full_sweep=True,
        reason="runtime/api/conftest.py is shared pytest infrastructure",
        fallback_rule="shared_test_fixture",
        trigger_paths=("runtime/api/conftest.py",),
    )
    monkeypatch.setattr(
        impacted_tests, "selection_for", lambda *a, **k: selection
    )

    paths = watch_pytest._impacted_selection("main")

    out = capsys.readouterr().out
    assert paths == list(impacted_tests.TEST_ANCHORS)
    assert "watch_pytest full sweep: " in out
    assert "watch_pytest impacted-selection scope=full_sweep" in out
    assert "rule=shared_test_fixture" in out


def test_wrapper_passes_bounded_through_to_selection(monkeypatch) -> None:
    seen: dict = {}

    def record(repo_root, base, *, bounded=False):
        seen["bounded"] = bounded
        return Selection(full_sweep=False, reason="ok", tests=("a/test_b.py",))

    monkeypatch.setattr(impacted_tests, "selection_for", record)

    watch_pytest._impacted_selection("main", bounded=True)

    assert seen["bounded"] is True


def test_wrapper_rejects_bounded_without_impacted(capsys) -> None:
    exit_code = watch_pytest.main(["--bounded"])

    assert exit_code == 2
    assert "--bounded only applies with --impacted" in capsys.readouterr().err
