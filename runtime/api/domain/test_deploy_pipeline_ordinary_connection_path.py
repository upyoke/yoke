"""End-to-end proof: the real connection resolver picks an ordinary active
HTTPS connection for every deploy GitHub Actions call shape.

Unlike the mocked-resolver unit coverage in test_deploy_pipeline_github_relay.py,
these tests write a genuine machine-config file holding only an active HTTPS
connection (no *-db-admin sibling, no local App key) and let the real
resolve_https_connection / serving_control_plane_env chain run against it.
Only the external GitHub/subprocess boundary (_run_cmd) is faked.
"""

from __future__ import annotations

import json
import subprocess
from unittest import mock

from yoke_core.domain import (
    deploy_pipeline_failure,
    deploy_pipeline_gates,
    deploy_pipeline_github_workflow as workflow,
    deploy_pipeline_reporting,
)


def _write_synthetic_https_config(tmp_path, monkeypatch, *, env: str = "prod") -> None:
    """Isolate machine config to a throwaway directory with one https connection."""
    token_path = tmp_path / "token"
    token_path.write_text("test-token", encoding="utf-8")
    config = {
        "active_env": env,
        "connections": {
            env: {
                "transport": "https",
                "api_url": "https://example.invalid/api",
                "credential_source": {
                    "kind": "token_file",
                    "path": str(token_path),
                },
            }
        },
    }
    (tmp_path / "config.json").write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path))
    monkeypatch.delenv("YOKE_ENV", raising=False)
    monkeypatch.delenv(
        deploy_pipeline_reporting.GITHUB_ACTIONS_RELAY_ENV, raising=False
    )
    monkeypatch.delenv(
        deploy_pipeline_reporting.GITHUB_ACTIONS_LOCAL_AUTHORITY_ENV, raising=False
    )


def _completed(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=""
    )


def test_ci_gate_read_resolves_through_the_synthetic_connection(tmp_path, monkeypatch):
    _write_synthetic_https_config(tmp_path, monkeypatch)
    envelope = json.dumps({"success": True, "result": {"state": "passed"}})

    with (
        mock.patch.object(
            deploy_pipeline_gates, "project_ci_workflow_file", return_value="ci.yml"
        ),
        mock.patch.object(
            deploy_pipeline_reporting, "_run_cmd", return_value=_completed(envelope)
        ) as run_cmd,
    ):
        passed, message = deploy_pipeline_gates._check_ci_gate(
            "acme/widgets",
            "acme",
            60,
            branch="main",
        )

    assert passed is True
    assert "CI passed" in message
    assert run_cmd.call_args.args[0][3:5] == ["--env", "prod"]


def test_workflow_dispatch_resolves_through_the_synthetic_connection(
    tmp_path, monkeypatch
):
    _write_synthetic_https_config(tmp_path, monkeypatch)

    with mock.patch.object(
        deploy_pipeline_reporting, "_run_cmd", return_value=_completed("30968749771\n")
    ) as run_cmd:
        result = deploy_pipeline_reporting._github_actions(
            "trigger",
            "acme/widgets",
            "deploy.yml",
            "main",
            project="acme",
        )

    assert result.returncode == 0
    assert run_cmd.call_args.args[0][3:5] == ["--env", "prod"]


def test_poll_resolves_through_the_synthetic_connection(tmp_path, monkeypatch):
    _write_synthetic_https_config(tmp_path, monkeypatch)

    with mock.patch.object(
        deploy_pipeline_reporting,
        "_run_cmd",
        return_value=_completed("completed: success"),
    ) as run_cmd:
        rc, output = deploy_pipeline_reporting._poll_github_actions(
            "acme/widgets",
            "123",
            60,
            project="acme",
        )

    assert (rc, output) == (0, "completed: success")
    assert run_cmd.call_args.args[0][3:5] == ["--env", "prod"]


def test_failure_diagnostics_resolve_through_the_synthetic_connection(
    tmp_path, monkeypatch
):
    _write_synthetic_https_config(tmp_path, monkeypatch)

    with mock.patch.object(
        deploy_pipeline_failure.reporting,
        "_run_cmd",
        return_value=_completed("Terminal failing job: build"),
    ) as run_cmd:
        result = deploy_pipeline_failure._failure_trace_command("run-1")

    assert result.returncode == 0
    command = run_cmd.call_args.args[0]
    assert command[3:5] == ["--env", "prod"]
    assert command[-3:] == ["deployment-runs", "failure-trace", "run-1"]


def test_stage_only_connection_resolves_to_stage(tmp_path, monkeypatch):
    """The ordinary-connection path is not hardcoded to 'prod'."""
    _write_synthetic_https_config(tmp_path, monkeypatch, env="stage")

    with mock.patch.object(
        deploy_pipeline_reporting,
        "_run_cmd",
        return_value=_completed("completed: success"),
    ) as run_cmd:
        result = deploy_pipeline_reporting._github_actions(
            "poll",
            "acme/widgets",
            "123",
            project="acme",
        )

    assert result.returncode == 0
    assert run_cmd.call_args.args[0][3:5] == ["--env", "stage"]


def test_a_full_workflow_step_persists_success_via_the_synthetic_connection(
    tmp_path, monkeypatch
):
    """A whole github-actions-workflow stage step -- CI gate, dispatch, and
    poll -- runs through the real resolver end to end and reports success,
    not just the isolated per-call assertions the other tests give.
    """
    _write_synthetic_https_config(tmp_path, monkeypatch)
    checkout = tmp_path / "checkout"
    (checkout / ".git").mkdir(parents=True)
    seen_verbs: list[str] = []

    def routed_run_cmd(cmd, timeout=60):
        if cmd and cmd[0] == "git":
            return _completed(returncode=0)
        assert cmd[3:5] == ["--env", "prod"]
        verb = cmd[6]
        seen_verbs.append(verb)
        if verb == "check-ci":
            return _completed(
                json.dumps({"success": True, "result": {"state": "passed"}})
            )
        if verb == "trigger-once":
            return _completed("30968749771\n")
        if verb == "poll":
            return _completed("completed: success")
        raise AssertionError(f"unexpected github-actions verb {verb!r}")

    with (
        mock.patch.object(workflow, "_run_cmd", routed_run_cmd),
        mock.patch.object(deploy_pipeline_reporting, "_run_cmd", routed_run_cmd),
        mock.patch.object(
            deploy_pipeline_gates, "project_ci_workflow_file", return_value="ci.yml"
        ),
    ):
        rc, diagnostic = workflow._dispatch_github_actions_workflow(
            {"workflow": "deploy.yml", "reconcile_by_head_sha": False},
            name="publish",
            run_id="run-seq-1",
            member_items=[],
            github_repo="acme/widgets",
            project="acme",
            project_repo_path=str(checkout),
            timeout_min=1,
            fresh=False,
            gate_branch="main",
            release_lineage="a" * 40,
            sd="/tmp/sd",
        )

    assert (rc, diagnostic) == (0, "")
    assert seen_verbs == ["check-ci", "trigger-once", "poll"]
