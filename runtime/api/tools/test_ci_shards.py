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
