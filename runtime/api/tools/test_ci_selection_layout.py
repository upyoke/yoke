"""A selection shard is laid out exactly like a full CI shard."""

from __future__ import annotations

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
