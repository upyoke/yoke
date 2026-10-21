"""Sizing a change-scoped selection against the suite's duration profile."""

from __future__ import annotations

import json
from pathlib import Path

from yoke_core.tools import ci_shard_sizing as sizing
from yoke_core.tools import ci_shards


def test_a_selection_too_small_to_cut_stays_on_one_runner() -> None:
    # The fixed setup a second runner pays has to buy back more than it costs.
    assert sizing.split_count(0.0, 0) == 1
    assert sizing.split_count(sizing.MIN_SHARD_PROFILE_SECONDS - 1, 500) == 1


def test_a_large_selection_earns_shards_up_to_the_suite_count() -> None:
    assert sizing.split_count(sizing.MIN_SHARD_PROFILE_SECONDS * 3, 5_000) == 3
    assert (
        sizing.split_count(sizing.MIN_SHARD_PROFILE_SECONDS * 1_000, 50_000)
        == ci_shards.SHARD_COUNT
    )


def test_the_split_never_outnumbers_the_tests_it_knows_about() -> None:
    # A group holding no test reports "no tests ran" instead of a verdict.
    huge = sizing.MIN_SHARD_PROFILE_SECONDS * 1_000
    assert sizing.split_count(huge, 3) == 3
    assert sizing.split_count(huge, 0) == 1


def test_a_selection_past_a_whole_budget_earns_the_next_shard() -> None:
    # The regression this closes: a selection sized at 63 profiled seconds
    # took the one shard floor division bought it, then ran 748 tests in
    # 179.55s. The remainder past a whole budget is test time that has to
    # run somewhere, so it earns a runner instead of being dropped.
    assert sizing.MIN_SHARD_PROFILE_SECONDS == 60.0
    assert sizing.split_count(63.0, 494) == 2
    assert sizing.split_count(60.0, 494) == 1
    assert sizing.split_count(60.1, 494) == 2


def test_a_selection_smaller_than_one_budget_stays_on_one_runner() -> None:
    # Rounding up must not turn every tiny selection into two runners: below
    # a whole budget there is one shard's worth of work and one shard.
    assert sizing.split_count(0.4, 1) == 1
    assert sizing.split_count(59.9, 500) == 1


def test_a_selection_larger_than_the_fan_out_is_capped_at_it() -> None:
    assert ci_shards.SHARD_COUNT == 8
    assert sizing.split_count(8 * 60.0, 5_000) == 8
    assert sizing.split_count(8 * 60.0 + 1, 5_000) == 8
    assert sizing.split_count(50_000.0, 20_000) == 8


def test_a_shard_earned_by_a_remainder_still_has_tests_to_fill_it() -> None:
    # Ceiling division earns a shard from a remainder, so the profiled test
    # count still caps the fan-out: a group with no test in it reports "no
    # tests ran" rather than a verdict.
    assert sizing.split_count(63.0, 1) == 1
    assert sizing.split_count(300.0, 2) == 2


def _profile(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ci_shards.DURATIONS_PATH).write_text(
        json.dumps(
            {
                "runtime/api/test_a.py::test_one": 1.0,
                "runtime/api/test_a.py::test_two": 2.0,
                "runtime/harness/test_b.py::TestB::test_three": 4.0,
                "tests/test_c.py::test_four": 8.0,
            }
        ),
        encoding="utf-8",
    )
    return root


def test_profiled_size_matches_files_directories_and_node_ids(tmp_path) -> None:
    root = _profile(tmp_path)
    assert sizing.profiled_size(root, ["runtime/api/test_a.py"]) == (3.0, 2)
    assert sizing.profiled_size(root, ["runtime/harness/"]) == (4.0, 1)
    assert sizing.profiled_size(root, ["tests/test_c.py::test_four"]) == (8.0, 1)
    assert sizing.profiled_size(root, ["runtime/harness/test_b.py::TestB"]) == (
        4.0,
        1,
    )
    assert sizing.profiled_size(root, ["runtime/api/test_a.py", "tests/"]) == (
        11.0,
        3,
    )


def test_profiled_size_treats_equivalent_path_spellings_as_the_same_work(
    tmp_path,
) -> None:
    root = _profile(tmp_path)
    expected = sizing.profiled_size(root, ["runtime/api/"])
    assert expected == (3.0, 2)
    assert sizing.profiled_size(root, ["./runtime/api/"]) == expected
    assert sizing.profiled_size(root, [str(root / "runtime" / "api")]) == expected
    assert sizing.profiled_size(root, ["./runtime/api/test_a.py::test_one"]) == (
        1.0,
        1,
    )
    whole = (15.0, 4)
    assert sizing.profiled_size(root, ["."]) == whole
    assert sizing.profiled_size(root, [str(root)]) == whole


def test_profiled_size_drops_targets_outside_the_checkout(tmp_path) -> None:
    root = _profile(tmp_path)
    outsider = tmp_path / "elsewhere" / "runtime" / "api"
    outsider.mkdir(parents=True)
    assert sizing.profiled_size(root, [str(outsider)]) == (0.0, 0)
    assert sizing.profiled_size(root, [str(outsider), "runtime/api/"]) == (3.0, 2)


def test_a_selection_the_profile_has_never_seen_is_sized_at_zero(tmp_path) -> None:
    # An unseen test adds time this cannot measure, so the estimate is a
    # floor: it costs a shard, never coverage.
    root = _profile(tmp_path)
    assert sizing.profiled_size(root, ["runtime/api/test_new.py"]) == (0.0, 0)


def test_an_unreadable_profile_sizes_to_one_runner(tmp_path) -> None:
    empty = tmp_path / "bare"
    empty.mkdir()
    seconds, profiled = sizing.profiled_size(empty, ["runtime/api/test_a.py"])
    assert (seconds, profiled) == (0.0, 0)
    assert sizing.split_count(seconds, profiled) == 1


def _suite(tmp_path: Path, selected: float, rest: float) -> Path:
    """A profile with one selectable file and the rest of the suite beside it."""
    root = tmp_path / "suite"
    root.mkdir()
    durations = {"picked/test_one.py::test_case": selected}
    durations.update(
        {f"rest/test_{index}.py::test_case": rest / 100 for index in range(100)}
    )
    (root / ci_shards.DURATIONS_PATH).write_text(
        json.dumps(durations), encoding="utf-8"
    )
    return root


def test_a_small_selection_runs_and_names_its_size(tmp_path) -> None:
    root = _suite(tmp_path, selected=90.0, rest=9_910.0)
    estimate = sizing.selection_estimate(root, ["picked/"])

    assert (estimate.seconds, estimate.tests) == (90.0, 1)
    assert round(estimate.suite_seconds, 6) == 10_000.0
    assert round(estimate.share, 6) == 0.009
    assert estimate.full_ci_reason == ""
    assert estimate.summary() == (
        "profiled_tests=1 profiled_seconds=90 suite_seconds=10000 "
        "share=0.009 shards=1"
    )


def test_a_selection_at_the_share_threshold_is_full_ci_work(tmp_path) -> None:
    total = 10_000.0
    selected = total * sizing.FULL_CI_SHARE
    root = _suite(tmp_path, selected=selected, rest=total - selected)

    reason = sizing.selection_estimate(root, ["picked/"]).full_ci_reason

    assert reason.startswith("selection_exceeds_full_ci_share: ")
    assert f"{sizing.FULL_CI_SHARE:.0%} of the suite's 10000s" in reason


def test_a_near_full_selection_is_full_ci_work(tmp_path) -> None:
    root = _suite(tmp_path, selected=10.0, rest=990.0)

    estimate = sizing.selection_estimate(root, ["picked/", "rest/"])

    assert round(estimate.share, 6) == 1.0
    assert estimate.full_ci_reason.startswith("selection_exceeds_full_ci_share")


def test_a_selection_whose_shard_carries_a_full_ci_load_is_full_ci_work(
    monkeypatch,
) -> None:
    # Below a raised share threshold, a selection whose few profiled tests
    # cannot be split carries more per shard than a full CI shard does, so
    # it would finish no sooner than full CI.
    monkeypatch.setattr(sizing, "FULL_CI_SHARE", 0.5)
    suite = 8_000.0
    estimate = sizing.SelectionEstimate(seconds=2_000.0, tests=1, suite_seconds=suite)

    assert estimate.shards == 1
    assert estimate.full_ci_reason == (
        "selection_not_faster_than_full_ci: each of its 1 shards carries 2000s; "
        "full CI's carry 1000s"
    )


def test_without_a_profile_there_is_nothing_to_compare_and_the_selection_runs(
    tmp_path,
) -> None:
    estimate = sizing.selection_estimate(tmp_path, ["anything/"])

    assert (estimate.seconds, estimate.suite_seconds) == (0.0, 0.0)
    assert estimate.full_ci_reason == ""
