"""Cutting one CI selection across runners: coverage, verdict, empty groups."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from yoke_core.tools import ci_selection_run as runner
from yoke_core.tools.ci_shards import DURATIONS_PATH


@pytest.fixture()
def sharded_repo(tmp_path: Path) -> Path:
    """A checkout of six independent tests with a duration for each."""
    root = tmp_path / "repo"
    root.mkdir()
    durations = {}
    for index in range(6):
        name = f"test_case_{index}.py"
        (root / name).write_text(f"def test_case_{index}():\n    assert True\n")
        durations[f"{name}::test_case_{index}"] = float(index + 1)
    (root / DURATIONS_PATH).write_text(json.dumps(durations), encoding="utf-8")
    return root


def _shard_args(root: Path) -> list[str]:
    return [
        *sorted(path.name for path in root.glob("test_case_*.py")),
        "-n", "0", "-v", "-p", "no:cacheprovider",
    ]


def _run_shard(root: Path, tmp_path: Path, *, splits: int, group: int) -> tuple[int, str]:
    log = tmp_path / f"shard-{group}-of-{splits}.txt"
    status = runner.run_selection(
        root,
        base_sha="",
        expected_head_sha="",
        passthrough=_shard_args(root),
        splits=splits,
        group=group,
        log_path=log,
    )
    return status, log.read_text(encoding="utf-8")


def _tests_that_ran(log_text: str) -> list[str]:
    return re.findall(r"(test_case_\d+\.py::test_case_\d+) PASSED", log_text)


def test_the_shards_cover_the_selection_exactly_once(
    sharded_repo: Path, tmp_path: Path,
) -> None:
    """The trap: a split that drops or repeats a test still reports green."""
    splits = 3
    ran: list[str] = []
    for group in range(1, splits + 1):
        status, log_text = _run_shard(sharded_repo, tmp_path, splits=splits, group=group)
        assert status == 0
        ran.extend(_tests_that_ran(log_text))

    expected = {
        f"test_case_{index}.py::test_case_{index}" for index in range(6)
    }
    assert sorted(ran) == sorted(expected), "every selected test runs in one group"
    assert len(ran) == len(expected), "and in no more than one"


def test_one_failing_shard_is_the_run_verdict(
    sharded_repo: Path, tmp_path: Path,
) -> None:
    (sharded_repo / "test_case_2.py").write_text(
        "def test_case_2():\n    assert False\n"
    )
    splits = 3
    statuses = [
        _run_shard(sharded_repo, tmp_path, splits=splits, group=group)[0]
        for group in range(1, splits + 1)
    ]
    assert statuses.count(0) == splits - 1
    assert any(status not in (0, runner.EXIT_NO_TESTS_COLLECTED) for status in statuses)


def test_a_group_the_split_left_empty_passes_and_says_so(
    sharded_repo: Path, tmp_path: Path, capsys,
) -> None:
    for index in range(2, 6):
        (sharded_repo / f"test_case_{index}.py").unlink()
    splits = 4  # more groups than there are tests to fill them
    ran: list[str] = []
    for group in range(1, splits + 1):
        status, log_text = _run_shard(sharded_repo, tmp_path, splits=splits, group=group)
        assert status == 0
        ran.extend(_tests_that_ran(log_text))

    assert sorted(ran) == [
        "test_case_0.py::test_case_0", "test_case_1.py::test_case_1",
    ]
    assert "drew no test from the split" in capsys.readouterr().out


def test_a_selection_that_matches_nothing_stays_a_failure(
    sharded_repo: Path, tmp_path: Path, capsys,
) -> None:
    """An empty group passes only because the other groups carry the work."""
    log = tmp_path / "filtered.txt"
    status = runner.run_selection(
        sharded_repo,
        base_sha="",
        expected_head_sha="",
        passthrough=[*_shard_args(sharded_repo), "-k", "matches_no_test_at_all"],
        splits=2,
        group=1,
        log_path=log,
    )
    assert status == runner.EXIT_NO_TESTS_COLLECTED
    assert "match nothing in this tree" in capsys.readouterr().out


def test_a_group_outside_the_split_refuses_rather_than_running(
    sharded_repo: Path, tmp_path: Path, capsys,
) -> None:
    """The matrix and the split come from one plan; disagreement is a defect."""
    status = runner.run_selection(
        sharded_repo,
        base_sha="",
        expected_head_sha="",
        passthrough=_shard_args(sharded_repo),
        splits=2,
        group=3,
        log_path=tmp_path / "unused.txt",
    )
    assert status == runner.EXIT_USAGE
    assert "group 3 of 2" in capsys.readouterr().out


def test_the_split_is_added_only_when_there_is_more_than_one_shard() -> None:
    assert "--splits" not in runner.pytest_command(["a.py"], [], splits=1, group=1)
    sharded = runner.pytest_command(["a.py"], [], splits=4, group=2)
    assert sharded[sharded.index("--splits") + 1] == "4"
    assert sharded[sharded.index("--group") + 1] == "2"
    assert sharded[sharded.index("--splitting-algorithm") + 1] == "least_duration"
    assert sharded[sharded.index("--durations-path") + 1] == DURATIONS_PATH
