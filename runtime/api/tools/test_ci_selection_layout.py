"""A selection shard is laid out exactly like a full CI shard."""

from __future__ import annotations

import os
import subprocess

import pytest

from yoke_core.domain.yaml_helper import load_document
from yoke_core.tools._source_pythonpath import repo_root

GITHUB = repo_root() / ".github"
RUNNER_ACTION = "./.github/actions/yoke-test-runner"


def _jobs(name: str) -> dict:
    return load_document(GITHUB / "workflows" / name)["jobs"]


def _step(job: dict, uses: str) -> dict:
    matches = [step for step in job["steps"] if step.get("uses", "").startswith(uses)]
    assert len(matches) == 1, f"expected one {uses} step"
    return matches[0]


def _names(job: dict) -> list[str]:
    return [step.get("name", "") for step in job["steps"]]


def test_both_shard_kinds_prepare_their_runner_with_the_same_action() -> None:
    full = _step(_jobs("yoke-ci.yml")["test_shard"], RUNNER_ACTION)
    selection = _step(_jobs("yoke-tests-selection.yml")["selection"], RUNNER_ACTION)

    assert full["with"]["python-version"] == "${{ matrix.python-version }}"
    assert selection["with"]["python-version"] == (
        "${{ needs.plan.outputs.python_latest }}"
    )
    assert full["with"]["pg-container"] == selection["with"]["pg-container"] == (
        "${{ env.PG_CONTAINER }}"
    )


def test_the_shared_action_owns_every_setup_step() -> None:
    action = load_document(GITHUB / "actions" / "yoke-test-runner" / "action.yml")
    steps = [step["name"] for step in action["runs"]["steps"]]
    for name in (
        "Reclaim runner disk",
        "Install dependencies",
        "Install TypeScript compiler",
        "Register libpython with the system loader cache",
        "Start Postgres (durability off, dynamic host port)",
        "Verify Postgres CREATEDB",
    ):
        assert name in steps
    for job in (
        _jobs("yoke-ci.yml")["test_shard"],
        _jobs("yoke-tests-selection.yml")["selection"],
    ):
        assert not set(_names(job)) & set(steps), "setup lives only in the action"


def test_selection_runs_on_the_full_suite_python_with_whole_file_splitting() -> None:
    jobs = _jobs("yoke-tests-selection.yml")
    plan = jobs["plan"]
    fan_out = next(step for step in plan["steps"] if step.get("id") == "fan_out")
    assert "yoke_core.tools.ci_shards fan-out" in fan_out["run"]
    assert plan["outputs"]["python_latest"] == (
        "${{ steps.fan_out.outputs.python_latest }}"
    )
    setup = _step(plan, "actions/setup-python")
    assert setup["with"]["python-version"] == (
        "${{ steps.fan_out.outputs.python_latest }}"
    )
    assert jobs["selection"]["env"]["YOKE_CI_PYTHON_SCOPE"] == "all"
    text = (GITHUB / "workflows" / "yoke-tests-selection.yml").read_text()
    assert "python-version: '3." not in text


def test_the_plan_refreshes_the_profile_every_shard_splits_with() -> None:
    jobs = _jobs("yoke-tests-selection.yml")
    plan = jobs["plan"]
    names = _names(plan)
    refresh = names.index("Refresh shard timing profile from retained CI reports")
    share = names.index("Share the timing profile with every shard")
    sizing = names.index("Publish the shard fan-out and split count")
    assert refresh < share < sizing, "the plan sizes against the profile it shares"
    assert plan["permissions"]["actions"] == "read"
    assert _step(plan, "actions/upload-artifact")["with"]["name"] == (
        "ci-test-durations"
    )

    selection = jobs["selection"]
    download = _step(selection, "actions/download-artifact")
    assert download["with"]["name"] == "ci-test-durations"
    selection_names = _names(selection)
    assert selection_names.index(download["name"]) < selection_names.index(
        "Run the selection"
    )


@pytest.mark.parametrize(
    ("runner", "installed", "expected"),
    [("self-hosted", False, 1), ("self-hosted", True, 0),
     ("github-hosted", False, 0), ("github-hosted", True, 0)],
)
def test_runner_prerequisites_install_only_on_hosted_hosts(
    tmp_path, runner, installed, expected,
) -> None:
    action = load_document(GITHUB / "actions" / "yoke-test-runner" / "action.yml")
    step = next(s for s in action["runs"]["steps"]
                if s["name"] == "Prepare runner prerequisites")
    commands = tmp_path / "commands"
    commands.mkdir()
    query = commands / "dpkg-query"
    query.write_text("#!/bin/bash\nprintf '%s' "+
                     ("'install ok installed'" if installed else "'not installed'"))
    sudo = commands / "sudo"
    sudo.write_text('#!/bin/bash\nprintf "%s\\n" "$*" >> "$CALLS"\n'
                    'if [[ "$1" == tee ]]; then cat >/dev/null; fi\n')
    query.chmod(0o755)
    sudo.chmod(0o755)
    calls = tmp_path / "calls"
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c",
         "source() { VERSION_CODENAME=resolute; }\n" + step["run"]],
        env={**os.environ, "PATH": f"{commands}:{os.environ['PATH']}",
             "RUNNER_ENVIRONMENT": runner, "CALLS": str(calls)},
        text=True, capture_output=True,
    )
    assert result.returncode == expected, result.stderr
    if expected:
        assert "ci_runner_prerequisites_missing: postgresql-client-16" in result.stderr
        assert "Install these packages from PGDG" in result.stderr
    if runner == "github-hosted" and not installed:
        operations = calls.read_text()
        assert "https://www.postgresql.org/media/keys/ACCC4CF8.asc" in operations
        assert "apt-get update" in operations
        assert "apt-get install --yes --no-install-recommends postgresql-client-16" in operations
        assert "libxml" not in operations
    else:
        assert not calls.exists(), "self-hosted and prepared hosts must stay unchanged"
