"""The shard fan-out and the split it selects come from one source."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from yoke_core.tools import ci_shards


REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "yoke-ci.yml"


def _workflow() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_fan_out_is_the_shard_list_as_json() -> None:
    lines = ci_shards.fan_out_lines()
    assert len(lines) == 1
    key, _, value = lines[0].partition("=")
    assert key == "shards"
    assert json.loads(value) == ci_shards.shard_list()
    assert ci_shards.shard_list() == list(range(1, ci_shards.SHARD_COUNT + 1))


def test_the_split_matches_the_fan_out_that_produced_the_group() -> None:
    command = ci_shards.pytest_command(3)
    assert command[command.index("--splits") + 1] == str(ci_shards.SHARD_COUNT)
    assert command[command.index("--group") + 1] == "3"
    assert command[command.index("--splits") + 1] == str(len(ci_shards.shard_list()))


def test_every_shard_the_fan_out_names_is_runnable() -> None:
    for shard in ci_shards.shard_list():
        assert ci_shards.pytest_command(shard)[-1].endswith(ci_shards.JUNIT_REPORT)


def test_a_group_outside_the_fan_out_refuses_rather_than_running() -> None:
    with pytest.raises(SystemExit, match=f"1..{ci_shards.SHARD_COUNT}"):
        ci_shards._run_shard(ci_shards.SHARD_COUNT + 1)
    with pytest.raises(SystemExit):
        ci_shards._run_shard(0)


def test_a_selection_too_small_to_cut_stays_on_one_runner() -> None:
    # The fixed setup a second runner pays has to buy back more than it costs.
    assert ci_shards.split_count(0.0, 0) == 1
    assert ci_shards.split_count(ci_shards.MIN_SHARD_PROFILE_SECONDS - 1, 500) == 1


def test_a_large_selection_earns_shards_up_to_the_suite_count() -> None:
    assert ci_shards.split_count(ci_shards.MIN_SHARD_PROFILE_SECONDS * 3, 5_000) == 3
    assert (
        ci_shards.split_count(ci_shards.MIN_SHARD_PROFILE_SECONDS * 1_000, 50_000)
        == ci_shards.SHARD_COUNT
    )


def test_the_split_never_outnumbers_the_tests_it_knows_about() -> None:
    # A group holding no test reports "no tests ran" instead of a verdict.
    huge = ci_shards.MIN_SHARD_PROFILE_SECONDS * 1_000
    assert ci_shards.split_count(huge, 3) == 3
    assert ci_shards.split_count(huge, 0) == 1


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
    assert ci_shards.profiled_size(root, ["runtime/api/test_a.py"]) == (3.0, 2)
    assert ci_shards.profiled_size(root, ["runtime/harness/"]) == (4.0, 1)
    assert ci_shards.profiled_size(
        root, ["tests/test_c.py::test_four"]
    ) == (8.0, 1)
    assert ci_shards.profiled_size(
        root, ["runtime/harness/test_b.py::TestB"]
    ) == (4.0, 1)
    assert ci_shards.profiled_size(root, ["runtime/api/test_a.py", "tests/"]) == (
        11.0, 3,
    )


def test_profiled_size_treats_equivalent_path_spellings_as_the_same_work(
    tmp_path,
) -> None:
    root = _profile(tmp_path)
    expected = ci_shards.profiled_size(root, ["runtime/api/"])
    assert expected == (3.0, 2)
    assert ci_shards.profiled_size(root, ["./runtime/api/"]) == expected
    assert ci_shards.profiled_size(root, [str(root / "runtime" / "api")]) == expected
    assert ci_shards.profiled_size(
        root, ["./runtime/api/test_a.py::test_one"]
    ) == (1.0, 1)
    whole = (15.0, 4)
    assert ci_shards.profiled_size(root, ["."]) == whole
    assert ci_shards.profiled_size(root, [str(root)]) == whole


def test_profiled_size_drops_targets_outside_the_checkout(tmp_path) -> None:
    root = _profile(tmp_path)
    outsider = tmp_path / "elsewhere" / "runtime" / "api"
    outsider.mkdir(parents=True)
    assert ci_shards.profiled_size(root, [str(outsider)]) == (0.0, 0)
    assert ci_shards.profiled_size(
        root, [str(outsider), "runtime/api/"]
    ) == (3.0, 2)


def test_a_selection_the_profile_has_never_seen_is_sized_at_zero(tmp_path) -> None:
    # An unseen test adds time this cannot measure, so the estimate is a
    # floor: it costs a shard, never coverage.
    root = _profile(tmp_path)
    assert ci_shards.profiled_size(root, ["runtime/api/test_new.py"]) == (0.0, 0)


def test_an_unreadable_profile_sizes_to_one_runner(tmp_path) -> None:
    empty = tmp_path / "bare"
    empty.mkdir()
    seconds, profiled = ci_shards.profiled_size(empty, ["runtime/api/test_a.py"])
    assert (seconds, profiled) == (0.0, 0)
    assert ci_shards.split_count(seconds, profiled) == 1


def test_a_shard_number_the_workflow_left_empty_is_the_unsharded_default() -> None:
    assert ci_shards.shard_number("") == 1
    assert ci_shards.shard_number("  ") == 1
    assert ci_shards.shard_number("4") == 4


def test_a_shard_number_that_is_not_one_refuses_rather_than_guessing() -> None:
    for value in ("0", "-2", "two", "1.5"):
        with pytest.raises(SystemExit, match="positive integer"):
            ci_shards.shard_number(value)


def test_the_suite_is_all_three_anchors() -> None:
    # A partial anchor demotes a package's top-level conftest and collection
    # fails, so the roots are asserted rather than left to a caller.
    assert ci_shards.SUITE_PATHS == (
        "runtime/api/", "runtime/harness/", "tests/",
    )
    command = ci_shards.pytest_command(1)
    for root in ci_shards.SUITE_PATHS:
        assert root in command


def test_the_workflow_names_neither_the_shard_list_nor_the_split() -> None:
    # The trap this guards: a matrix of N against --splits M runs a fraction
    # of the suite and still reports green, because each job passes the slice
    # it was handed. Neither number may be written in the workflow.
    workflow = _workflow()
    assert (
        "shard: ${{ fromJSON(needs.repo_contracts.outputs.shards) }}" in workflow
    )
    assert "yoke_core.tools.ci_shards fan-out --write-github-output" in workflow
    assert "yoke_core.tools.ci_shards run" in workflow
    assert re.search(r"--splits\s+\d", workflow) is None
    assert re.search(r"shard:\s*\[", workflow) is None


def test_the_queue_requires_every_shard_the_fan_out_produces() -> None:
    # A shard the ruleset does not require can fail without blocking a merge.
    declaration = json.loads(
        (REPO_ROOT / ".yoke" / "merge-queue.json").read_text(encoding="utf-8")
    )
    rules = declaration["ruleset"]["rules"]
    checks = next(
        rule for rule in rules if rule["type"] == "required_status_checks"
    )["parameters"]["required_status_checks"]
    required = {row["context"] for row in checks}
    workflow = _workflow()
    versions = re.search(
        r"python-version: \[([^\]]+)\]", workflow
    ).group(1).replace("'", "").split(", ")
    expected = {
        f"test-shard ({version}, {shard})"
        for version in versions
        for shard in ci_shards.shard_list()
    }
    assert expected <= required


def test_the_fan_out_writes_the_github_output_file(tmp_path, monkeypatch) -> None:
    output = tmp_path / "github_output"
    output.write_text("existing=1\n", encoding="utf-8")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))

    assert ci_shards.main(["fan-out", "--write-github-output"]) == 0

    written = output.read_text(encoding="utf-8").splitlines()
    assert written[0] == "existing=1"
    assert written[1:] == ci_shards.fan_out_lines()


def test_the_fan_out_prints_when_no_output_file_is_named(capsys, monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)

    assert ci_shards.main(["fan-out"]) == 0

    assert capsys.readouterr().out.strip() == "\n".join(ci_shards.fan_out_lines())
