"""Rebuilding the timing profile from a full-suite run's shard artifacts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_core.tools import ci_durations_refresh as refresher
from yoke_core.tools import ci_shards


def _shard_artifact(
    artifacts: Path,
    root: Path,
    *,
    python_version: str,
    shard: int,
    wall_seconds: float,
    cases: dict[tuple[str, str], float],
) -> None:
    """One shard's uploaded report, plus the modules its classnames name."""
    for classname, _ in cases:
        module = root / (classname.split(".")[0] + ".py")
        module.parent.mkdir(parents=True, exist_ok=True)
        module.touch()
    body = "".join(
        f'<testcase classname="{classname}" name="{name}" time="{seconds}"/>'
        for (classname, name), seconds in cases.items()
    )
    directory = artifacts / f"pytest-output-{python_version}-{shard}"
    directory.mkdir(parents=True)
    (directory / ci_shards.JUNIT_REPORT).write_text(
        f'<testsuites><testsuite time="{wall_seconds}">{body}</testsuite></testsuites>',
        encoding="utf-8",
    )


@pytest.fixture()
def measured(tmp_path: Path) -> tuple[Path, Path]:
    """A two-shard run whose cases sum to four times its session wall time."""
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    root = tmp_path / "repo"
    root.mkdir()
    _shard_artifact(
        artifacts,
        root,
        python_version="3.13",
        shard=1,
        wall_seconds=10.0,
        cases={("mod_a", "test_one"): 30.0, ("mod_a", "test_two"): 10.0},
    )
    _shard_artifact(
        artifacts,
        root,
        python_version="3.13",
        shard=2,
        wall_seconds=10.0,
        cases={("mod_b.TestGroup", "test_three"): 40.0},
    )
    return artifacts, root


def test_a_case_is_stored_as_its_share_of_the_wall_time_spent(measured) -> None:
    # The whole point of normalizing: raw junit seconds are measured under
    # `-n auto`, so their sum (80s here) exceeds the wall time the session
    # took (20s). Storing them raw would inflate every later estimate.
    artifacts, root = measured
    shards = refresher.read_shards(artifacts, root, "3.13")
    profile = refresher.normalized_profile(shards)

    assert sum(profile.values()) == pytest.approx(20.0)
    assert profile["mod_a.py::test_one"] == pytest.approx(7.5)
    assert profile["mod_a.py::test_two"] == pytest.approx(2.5)
    assert profile["mod_b.py::TestGroup::test_three"] == pytest.approx(10.0)


def test_the_stored_profile_never_exceeds_the_wall_time_it_measured(
    measured,
) -> None:
    # The inversion this guards against scales the other way and hands every
    # future selection an estimate several times the work it will do.
    artifacts, root = measured
    shards = refresher.read_shards(artifacts, root, "3.13")

    measured_cost = sum(sum(shard.case_seconds.values()) for shard in shards)
    wall = sum(shard.wall_seconds for shard in shards)
    assert measured_cost > wall

    assert sum(refresher.normalized_profile(shards).values()) == pytest.approx(wall)


def test_normalizing_leaves_every_weight_relative_to_every_other(measured) -> None:
    # `least_duration` balances on relative weight alone, so scaling must not
    # reorder or re-proportion anything.
    artifacts, root = measured
    shards = refresher.read_shards(artifacts, root, "3.13")
    raw = refresher.merged_case_seconds(shards)
    profile = refresher.normalized_profile(shards)

    assert list(profile) == sorted(raw)
    for node in raw:
        assert profile[node] / profile["mod_a.py::test_two"] == pytest.approx(
            raw[node] / raw["mod_a.py::test_two"]
        )


def test_a_junit_classname_resolves_through_the_checkout(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "test_thing.py").touch()

    cache: dict[str, bool] = {}
    assert (
        refresher.node_id(root, "pkg.test_thing.TestOuter", "test_case[1]", cache)
        == "pkg/test_thing.py::TestOuter::test_case[1]"
    )
    assert refresher.node_id(root, "pkg.test_thing", "test_plain", cache) == (
        "pkg/test_thing.py::test_plain"
    )


def test_a_classname_this_checkout_cannot_place_refuses(tmp_path: Path) -> None:
    # Naming a test the tree does not hold means the run and the checkout are
    # different commits, and the profile would record tests that do not exist.
    with pytest.raises(SystemExit, match="no module file"):
        refresher.node_id(tmp_path, "gone.test_removed", "test_case", {})


def test_a_test_two_shards_both_ran_refuses(tmp_path: Path) -> None:
    # The split gives each test to one group, so an overlap means the run
    # under measurement did not cover the suite exactly once.
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    root = tmp_path / "repo"
    root.mkdir()
    for shard in (1, 2):
        _shard_artifact(
            artifacts,
            root,
            python_version="3.13",
            shard=shard,
            wall_seconds=1.0,
            cases={("mod_a", "test_one"): 1.0},
        )

    shards = refresher.read_shards(artifacts, root, "3.13")
    with pytest.raises(SystemExit, match="more than one shard"):
        refresher.merged_case_seconds(shards)


def test_a_run_covering_several_python_versions_asks_which_to_store(
    tmp_path: Path,
) -> None:
    # Each version covers the suite once, so storing both would carry every
    # test's time twice.
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    root = tmp_path / "repo"
    root.mkdir()
    for version in ("3.10", "3.13"):
        _shard_artifact(
            artifacts,
            root,
            python_version=version,
            shard=1,
            wall_seconds=1.0,
            cases={("mod_a", "test_one"): 1.0},
        )

    assert refresher.python_versions(artifacts) == ["3.10", "3.13"]
    with pytest.raises(SystemExit, match="--python-version"):
        refresher.refresh(artifacts, root, None)
    with pytest.raises(SystemExit, match="holds no 3.12 shards"):
        refresher.refresh(artifacts, root, "3.12")


def test_a_selection_run_cannot_refresh_the_profile(tmp_path: Path) -> None:
    # A selection covers only its own change; a profile rebuilt from one
    # would forget every test the selection did not reach.
    artifacts = tmp_path / "artifacts"
    (artifacts / "pytest-output-selection-1").mkdir(parents=True)
    root = tmp_path / "repo"
    root.mkdir()

    assert refresher.python_versions(artifacts) == []
    with pytest.raises(SystemExit, match="name a full-suite run instead"):
        refresher.refresh(artifacts, root, None)


def test_the_refresh_writes_the_profile_the_sizing_rule_reads(measured) -> None:
    artifacts, root = measured

    assert refresher.refresh(artifacts, root, "3.13") == 0

    written = json.loads((root / ci_shards.DURATIONS_PATH).read_text(encoding="utf-8"))
    assert written == refresher.normalized_profile(
        refresher.read_shards(artifacts, root, "3.13")
    )
    seconds, profiled = ci_shards.profiled_size(root, ["mod_a.py"])
    assert (seconds, profiled) == (pytest.approx(10.0), 2)


def test_the_committed_profile_has_the_shape_a_refresh_leaves_behind() -> None:
    # The profile is committed data, so what keeps it honest is that one
    # command rebuilds it. These are the properties a refresh always leaves
    # and a hand-edited entry would not.
    repo = Path(__file__).resolve().parents[3]
    profile = json.loads(
        (repo / ci_shards.DURATIONS_PATH).read_text(encoding="utf-8")
    )
    assert profile
    assert list(profile) == sorted(profile)
    assert all(seconds >= 0.0 for seconds in profile.values())
    assert all(node.split("::")[0].endswith(".py") for node in profile)
