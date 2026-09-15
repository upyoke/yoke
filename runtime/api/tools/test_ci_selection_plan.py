"""Sizing a dispatched selection, and publishing the fan-out it earns."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_core.tools import ci_selection_plan as planner
from yoke_core.tools import ci_shards
from yoke_core.tools.ci_selection_run import EXIT_USAGE


@pytest.fixture()
def profiled_repo(tmp_path: Path) -> Path:
    """A checkout whose profile makes one directory worth several shards."""
    root = tmp_path / "repo"
    root.mkdir()
    durations = {
        f"big/test_{index}.py::test_case": ci_shards.MIN_SHARD_PROFILE_SECONDS
        for index in range(3)
    }
    durations["small/test_quick.py::test_case"] = 0.5
    (root / ci_shards.DURATIONS_PATH).write_text(
        json.dumps(durations), encoding="utf-8"
    )
    return root


def test_the_fan_out_and_the_split_count_are_the_same_number() -> None:
    assert planner.plan_lines(1) == ["shards=[1]", "splits=1"]
    assert planner.plan_lines(3) == ["shards=[1,2,3]", "splits=3"]
    for count in (1, 2, ci_shards.SHARD_COUNT):
        shards, splits = planner.plan_lines(count)
        assert len(json.loads(shards.partition("=")[2])) == int(
            splits.partition("=")[2]
        )


def test_a_selection_is_sized_against_everything_it_will_collect(
    profiled_repo: Path,
) -> None:
    assert planner.plan(profiled_repo, base_sha="", passthrough=["big/"]) == 3
    assert planner.plan(profiled_repo, base_sha="", passthrough=["small/"]) == 1


def test_the_impacted_paths_and_the_dispatched_paths_are_both_sized(
    profiled_repo: Path, monkeypatch,
) -> None:
    monkeypatch.setattr(
        planner, "selection_paths", lambda root, base: ["big/test_0.py"],
    )
    targets = planner.selection_targets(
        profiled_repo, base_sha="b" * 40, passthrough=["-q", "small/test_quick.py"],
    )
    assert targets == ["big/test_0.py", "small/test_quick.py"]


def test_an_impacted_selection_that_found_nothing_plans_one_shard(
    profiled_repo: Path, monkeypatch,
) -> None:
    monkeypatch.setattr(planner, "selection_paths", lambda root, base: None)
    assert planner.plan(profiled_repo, base_sha="b" * 40, passthrough=[]) == 1


def test_the_plan_is_written_where_the_workflow_reads_it(
    profiled_repo: Path, tmp_path: Path, monkeypatch,
) -> None:
    output = tmp_path / "github_output"
    output.write_text("existing=1\n", encoding="utf-8")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))

    assert planner.main([
        "--root", str(profiled_repo), "--base-sha=", "--head-sha=",
        "--pytest-args=big/", "--write-github-output",
    ]) == 0

    assert output.read_text(encoding="utf-8").splitlines() == [
        "existing=1", "shards=[1,2,3]", "splits=3",
    ]


def test_a_plan_for_another_tree_refuses_rather_than_sizing_it(
    profiled_repo: Path, capsys,
) -> None:
    # A plan for a different commit would fan out for work this run is not
    # about, so the mismatch stops the run before any shard starts.
    code = planner.main([
        "--root", str(profiled_repo), "--base-sha=", "--head-sha=" + "f" * 40,
        "--pytest-args=big/",
    ])
    assert code == EXIT_USAGE
    assert "the dispatch named ffffffffffff" in capsys.readouterr().out
