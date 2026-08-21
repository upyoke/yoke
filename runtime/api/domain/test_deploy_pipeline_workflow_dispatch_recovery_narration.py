"""Recovery narration must never claim a fresh workflow dispatch."""

from __future__ import annotations

from contextlib import redirect_stdout
import io
import subprocess
from unittest import mock

from yoke_contracts.github_workflow_dispatch import (
    WORKFLOW_DISPATCH_DISPATCHED_MARKER,
    WORKFLOW_DISPATCH_RECOVERED_MARKER,
)
from yoke_core.domain import deploy_pipeline_github_workflow as workflow
from yoke_core.domain.deploy_pipeline_github_workflow_reconciliation import (
    DISPATCHED_RUN_NARRATION,
    FRESH_DISPATCH_CLAIM,
    RECOVERED_RUN_NARRATION,
    decode_trigger_result,
)


def _result(returncode: int, stdout: str = "", stderr: str = ""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def _hosted_release_config() -> dict[str, object]:
    return {
        "workflow": "platform-release-bridge.yml",
        "dispatch_correlation_input": "yoke_dispatch_id",
        "inputs": {"product_sha": "{head_sha}"},
        "ref": "main",
        "reconcile_by_head_sha": False,
        "wait_for_ci": False,
    }


def _dispatch(config: dict[str, object], tmp_path, *, github_actions):
    checkout = tmp_path / "repo"
    (checkout / ".git").mkdir(parents=True, exist_ok=True)
    captured = io.StringIO()
    with mock.patch.object(
        workflow, "_check_ci_gate", return_value=(True, ""),
    ), mock.patch.object(
        workflow, "_run_cmd", return_value=_result(0, "abc123\n"),
    ), mock.patch.object(
        workflow, "_github_actions", side_effect=github_actions,
    ), mock.patch.object(
        workflow, "_poll_github_actions", return_value=(0, "success"),
    ), redirect_stdout(captured):
        rc, diag = workflow._dispatch_github_actions_workflow(
            config,
            name="hosted-release",
            run_id="run-20260821-001",
            member_items=[],
            github_repo="upyoke/platform",
            project="yoke",
            project_repo_path=str(checkout),
            timeout_min=30,
            fresh=False,
            gate_branch="main",
            release_lineage="a" * 40,
            sd="/tmp/sd",
        )
    return rc, diag, captured.getvalue()


def test_decode_trigger_result_names_recovered_vs_dispatched() -> None:
    recovered = decode_trigger_result(_result(
        0, "32434951903\n", stderr=f"{WORKFLOW_DISPATCH_RECOVERED_MARKER}\n",
    ))
    dispatched = decode_trigger_result(_result(
        0, "99\n", stderr=f"{WORKFLOW_DISPATCH_DISPATCHED_MARKER}\n",
    ))
    unknown = decode_trigger_result(_result(0, "99\n"))
    assert recovered == ("32434951903", False)
    assert dispatched == ("99", True)
    assert unknown == ("99", None)


def test_recovered_correlation_does_not_claim_a_fresh_dispatch(tmp_path) -> None:
    def github_actions(*args: str, **_kwargs):
        if args and args[0] == "trigger":
            return _result(
                0,
                "32434951903\n",
                stderr=f"{WORKFLOW_DISPATCH_RECOVERED_MARKER}\n",
            )
        return _result(0)

    rc, diag, out = _dispatch(
        _hosted_release_config(), tmp_path, github_actions=github_actions,
    )

    assert (rc, diag) == (0, "")
    assert FRESH_DISPATCH_CLAIM not in out
    assert "triggering workflow_dispatch" not in out
    assert "will trigger workflow_dispatch" not in out
    assert RECOVERED_RUN_NARRATION in out
    assert DISPATCHED_RUN_NARRATION not in out
    assert "Workflow run ID: 32434951903" in out
    assert "skipping SHA-only existing-run search" in out


def test_fresh_correlated_dispatch_names_a_new_run(tmp_path) -> None:
    def github_actions(*args: str, **_kwargs):
        if args and args[0] == "trigger":
            return _result(
                0,
                "4455\n",
                stderr=f"{WORKFLOW_DISPATCH_DISPATCHED_MARKER}\n",
            )
        return _result(0)

    rc, diag, out = _dispatch(
        _hosted_release_config(), tmp_path, github_actions=github_actions,
    )

    assert (rc, diag) == (0, "")
    assert FRESH_DISPATCH_CLAIM not in out
    assert DISPATCHED_RUN_NARRATION in out
    assert RECOVERED_RUN_NARRATION not in out
    assert "Workflow run ID: 4455" in out


def test_uncorrelated_miss_still_names_a_fresh_dispatch(tmp_path) -> None:
    def github_actions(*args: str, **_kwargs):
        if args and args[0] == "trigger-once":
            return _result(0, "73\n")
        return _result(0)

    with mock.patch.object(
        workflow, "_find_existing_workflow_run", return_value=("", False, ""),
    ):
        rc, diag, out = _dispatch(
            {"workflow": "externalwebapp-deploy.yml"},
            tmp_path,
            github_actions=github_actions,
        )

    assert (rc, diag) == (0, "")
    assert FRESH_DISPATCH_CLAIM in out
    assert "Workflow run ID: 73" in out
    assert RECOVERED_RUN_NARRATION not in out
