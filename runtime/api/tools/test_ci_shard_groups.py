"""One published partition preserves coverage, scope and shared fixtures."""

import json
from pathlib import Path
import subprocess
import sys

import pytest

from yoke_core.tools import ci_shard_groups as grouping


def records():
    return [{"nodeid": f"tests/test_{name}.py::test_{case}",
             "wheel": name in "ab", "independent": name in "ab"}
            for name in "abcdef" for case in range(2)]


def test_partitions_cover_each_leg_exactly_once_and_keep_wheel_files_together():
    items = records()
    tracked = sorted({item["nodeid"].split("::")[0] for item in items})
    groups = grouping.build_groups(items, {}, tracked, count=2)
    for scope, partition in groups.items():
        expected = {item["nodeid"].split("::")[0] for item in items
                    if scope == "all" or not item["independent"]}
        assert set().union(*map(set, partition)) == expected
        assert sum(map(len, partition)) == len(expected)
    assert any({"tests/test_a.py", "tests/test_b.py"} <= set(group)
               for group in groups["all"])


def test_unknown_files_have_average_file_weight_and_deterministic_git_order():
    items = records()[4:]
    tracked = sorted({item["nodeid"].split("::")[0] for item in items})
    durations = {item["nodeid"]: 5 for item in items if "test_c.py" in item["nodeid"]}
    groups = grouping.group_files(items, durations, tracked, count=2)
    assert groups == [[tracked[0], tracked[2]], [tracked[1], tracked[3]]]
    assert grouping.group_files(list(reversed(items)), durations, tracked, 2) == groups


def test_untracked_collection_and_empty_groups_refuse():
    with pytest.raises(ValueError, match="ci_shard_files_untracked"):
        grouping.group_files(records(), {}, [], count=2)
    tracked = sorted({item["nodeid"].split("::")[0] for item in records()})
    with pytest.raises(ValueError, match="ci_shard_group_empty"):
        grouping.group_files(records(), {}, tracked, count=16)


@pytest.mark.parametrize("contents", ["{}", "bad json", '{"all": [[]]}'])
def test_bad_artifact_refuses_before_launching_pytest(tmp_path, contents):
    artifact = tmp_path / "groups.json"
    artifact.write_text(contents)
    with pytest.raises(SystemExit, match="ci_shard_groups_invalid.*regenerate"):
        grouping.shard_files(artifact, "all", 1)


def test_collection_filter_never_imports_an_unassigned_file(tmp_path):
    # Exercise the real collection filter across all three conftest anchors.
    for root in ("runtime/api", "runtime/harness", "tests"):
        directory = tmp_path / root
        directory.mkdir(parents=True)
        (directory / "conftest.py").write_text("pytest_plugins = []\n")
        (directory / "test_selected.py").write_text("def test_selected(): pass\n")
        (directory / "test_other.py").write_text("raise AssertionError('unassigned import')\n")
    selected = tmp_path / "selection.txt"
    selected.write_text("\n".join(f"{root}/test_selected.py"
                                for root in ("runtime/api", "runtime/harness", "tests")))
    import os
    environment = dict(os.environ, YOKE_CI_SELECTION_FILE=str(selected))
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "runtime/api/", "runtime/harness/", "tests/",
         "--collect-only", "-q", "-p", "yoke_core.tools.ci_selection_collect"],
        cwd=tmp_path, env=environment, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "3 tests collected" in result.stdout


def test_workflow_collects_once_alongside_wheels_before_shards():
    import yaml
    root = Path(__file__).resolve().parents[3]
    jobs = yaml.safe_load((root / ".github/workflows/yoke-ci.yml").read_text())["jobs"]
    run = next(step["run"] for step in jobs["repo_contracts"]["steps"]
               if step["name"] == "Build portable product wheels")
    assert "yoke_core.tools.ci_shard_groups &" in run
    assert 'wait "$grouping_pid"' in run
    downloads = [step.get("with", {}).get("name") for step in jobs["test_shard"]["steps"]]
    assert "ci-shard-groups" in downloads
