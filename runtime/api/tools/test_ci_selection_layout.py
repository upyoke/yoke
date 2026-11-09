"""A selection shard is laid out exactly like a full CI shard."""

from __future__ import annotations

from yoke_core.domain.yaml_helper import load_document
from yoke_core.domain.source_pythonpath import repo_root

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


def test_dependency_setup_caches_uv_downloads_instead_of_pip() -> None:
    action = load_document(GITHUB / "actions" / "yoke-test-runner" / "action.yml")
    setups = [_jobs("yoke-ci.yml")["reuse_coverage"],
              _jobs("yoke-tests-selection.yml")["plan"]]
    for setup in [action["runs"], *setups]:
        uv = _step(setup, "astral-sh/setup-uv@")
        revision = uv["uses"].split("@", 1)[1]
        assert len(revision) == 40 and all(c in "0123456789abcdef" for c in revision)
        assert uv["with"]["enable-cache"] is True
        assert uv["with"]["cache-dependency-glob"] == "uv.lock"
        assert "cache" not in _step(setup, "actions/setup-python")["with"]
        assert not any("pip install" in s.get("run", "") for s in setup["steps"])
        install = next(s for s in setup["steps"]
                       if "uv sync" in s.get("run", "")
                       or "yoke_core.tools.ci_runner_prepare" in s.get("run", ""))
        if setup in setups:
            assert install["run"] == "uv sync --all-packages --locked"
        else:
            assert "python3 -S -m yoke_core.tools.ci_runner_prepare" in install["run"]
        assert setup["steps"].index(uv) < setup["steps"].index(install)


def test_partial_fetch_keeps_versioning_and_git_test_history() -> None:
    jobs = _jobs("yoke-ci.yml")
    for name in ("test_shard", "reuse_coverage"):
        checkout = _step(jobs[name], "actions/checkout")["with"]
        assert checkout["fetch-depth"] == 0
        assert checkout["filter"] == "blob:none"
    for name in ("repo_contracts", "shard_coverage", "container"):
        assert _step(jobs[name], "actions/checkout")["with"]["fetch-depth"] == 0
    for job in _jobs("yoke-tests-selection.yml").values():
        assert _step(job, "actions/checkout")["with"]["fetch-depth"] == 0


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
        "Prepare runner prerequisites, dependencies and Postgres",
        "Install TypeScript compiler",
        "Register libpython with the system loader cache",
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


def test_full_ci_checks_and_refresh_run_beside_shared_collection() -> None:
    jobs = _jobs("yoke-ci.yml")
    collection = jobs["repo_contracts"]
    checks = jobs["reuse_coverage"]
    assert not collection.get("needs") and not checks.get("needs")
    assert "Build product wheels and collect shard files" in _names(collection)
    for name in (
        "Refresh shard timing profile from retained CI reports", "Run repo contracts",
        "Share the timing profile with every shard",
    ):
        assert name in _names(checks) and name not in _names(collection)
        step = next(step for step in checks["steps"] if step.get("name") == name)
        assert "if" not in step, "contracts and profile publication run on reused trees too"
    refresh = next(step for step in checks["steps"] if "ci_durations_refresh" in step.get("run", ""))
    assert refresh["continue-on-error"] is True, "missing telemetry must keep the baseline usable"
    assert _names(checks).index(refresh["name"]) < _names(checks).index(
        "Share the timing profile with every shard"
    )
    for name in ("test_shard", "shard_coverage", "browser_runtime"):
        assert {"repo_contracts", "reuse_coverage"} <= set(jobs[name]["needs"])
        assert "needs.reuse_coverage.result == 'success'" in jobs[name]["if"]
    artifacts = [step["with"]["name"] for step in checks["steps"]
                 if step.get("uses", "").startswith("actions/upload-artifact")]
    assert artifacts.count("ci-test-durations") == 1
