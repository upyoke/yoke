"""Tests for the GitHub Actions runner-fleet Pulumi template component."""

from __future__ import annotations

import base64

import pytest

from runtime.api.domain.test_webapp_registry_stack import (
    _Recorder,
    _load_template_module,
)


def _runner_stack(monkeypatch, *, shutdown_mode="terminate"):
    recorder = _Recorder()
    # The stack module imports its internals sibling at top level; the
    # template infra dir is not on sys.path under file-location loading, so
    # load the internals module against the same recorder and inject it under
    # its bare runtime name before the stack import runs.
    internals = _load_template_module(
        monkeypatch, recorder, "webapp_runner_fleet_internals.py",
    )
    module = _load_template_module(
        monkeypatch, recorder, "webapp_runner_fleet_stack.py",
        extra_modules={"webapp_runner_fleet_internals": internals},
    )
    stack = module.WebappRunnerFleetStack(
        "yoke-runner-fleet",
        module.WebappRunnerFleetArgs(
            project_name="yoke",
            github_repo="upyoke/yoke",
            runner_labels=[
                "self-hosted", "Linux", "ARM64", "yoke-github-actions",
            ],
            runner_count=4,
            max_runner_count=4,
            instance_type="m7g.2xlarge",
            architecture="arm64",
            root_volume_gb=100,
            idle_shutdown_minutes=30,
            shutdown_mode=shutdown_mode,
        ),
    )
    return recorder, stack


def test_launch_template_uses_selected_size_and_disposable_root(monkeypatch):
    recorder, _stack = _runner_stack(monkeypatch)
    launch_template = recorder.single("runnerFleetLaunchTemplate")

    assert launch_template.kwargs["instance_type"] == "m7g.2xlarge"
    block = launch_template.kwargs["block_device_mappings"][0]
    ebs = block.kwargs["ebs"]
    assert ebs.kwargs["volume_size"] == 100
    assert ebs.kwargs["volume_type"] == "gp3"
    assert ebs.kwargs["encrypted"] is True
    assert ebs.kwargs["delete_on_termination"] is True

    user_data = base64.b64decode(launch_template.kwargs["user_data"]).decode()
    assert "RUNNER_COUNT=4" in user_data
    assert "RUNNER_ARCH=\"arm64\"" in user_data
    assert "awscli-exe-linux-${AWSCLI_ARCH}.zip" in user_data
    assert "AWSCLI_ARCH=\"aarch64\"" in user_data
    assert "RUNNER_ASSET_PREFIX=\"actions-runner-linux-${RUNNER_ARCH}-\"" in user_data
    assert ".browser_download_url" in user_data
    assert "actions ALL=(ALL) NOPASSWD:ALL" in user_data
    assert "env HOME=/root PULUMI_HOME=/root/.pulumi" in user_data
    assert "PULUMI_BIN=/.pulumi/bin/pulumi" in user_data
    assert 'install -m 0755 "$PULUMI_BIN" /usr/bin/pulumi' in user_data
    assert '(cd "${dir}" && ./svc.sh install actions && ./svc.sh start)' in user_data
    assert "set-desired-capacity" in user_data
    assert "GITHUB_TOKEN_PARAMETER=\"/yoke/github-actions-runner-fleet/github-token\"" in user_data


def test_idle_reaper_deregisters_runners_before_scale_down(monkeypatch):
    recorder, _stack = _runner_stack(monkeypatch)
    launch_template = recorder.single("runnerFleetLaunchTemplate")
    user_data = base64.b64decode(launch_template.kwargs["user_data"]).decode()
    reaper_start = user_data.index("#!/usr/bin/env python3")
    reaper_end = user_data.index("\nPY", reaper_start)
    compile(user_data[reaper_start:reaper_end], "yoke-runner-idle-reaper", "exec")

    drain_index = user_data.index("def drain_runners(runners):")
    scale_index = user_data.index('"aws", "autoscaling", "set-desired-capacity"')
    assert drain_index < scale_index
    assert 'subprocess.run(\n                ["./svc.sh", "stop"]' in user_data
    assert "def reclaim_runner_disk():" in user_data
    assert 'os.path.join(runner_root, "runner-*", "_diag", "*.log")' in user_data
    assert 'os.path.join(runner_root, "runner-*", "_work", "*")' in user_data
    assert 'os.path.join(tmp_root, "pip-*")' in user_data
    assert 'os.path.basename(path).startswith("_")' in user_data
    assert '["docker", "buildx", "prune", "-af"]' in user_data
    assert '["docker", "system", "prune", "-af", "--volumes"]' in user_data
    assert 'github_api("/actions/runners/" + runner_id, method="DELETE")' in user_data
    assert "wait_for_github_removal(runner_ids, runner_names)" in user_data
    assert "stop_local_runner_services()\n    reclaim_runner_disk()" in user_data
    assert "drain_runners(matching)\n    run([" in user_data


def test_asg_starts_at_zero_and_keeps_one_disposable_host(monkeypatch):
    recorder, _stack = _runner_stack(monkeypatch)
    asg = recorder.single("runnerFleetAsg")

    assert asg.kwargs["name"] == "yoke-github-actions-runner-fleet"
    assert asg.kwargs["min_size"] == 0
    assert "desired_capacity" not in asg.kwargs
    assert asg.kwargs["max_size"] == 1
    assert asg.kwargs["vpc_zone_identifiers"] == ["subnet-a", "subnet-b"]
    assert asg.opts.ignore_changes == ["desiredCapacity"]


def test_webhook_lambda_is_hmac_backed_and_routes_matching_labels(monkeypatch):
    recorder, _stack = _runner_stack(monkeypatch)

    github_token = recorder.single("runnerFleetGithubToken")
    webhook_secret = recorder.single("runnerFleetWebhookSecret")
    assert github_token.kwargs["type"] == "SecureString"
    assert webhook_secret.kwargs["type"] == "SecureString"
    assert github_token.kwargs["value"] == "pending-runner-fleet-secret-bootstrap"
    assert webhook_secret.kwargs["value"] == "pending-runner-fleet-secret-bootstrap"
    assert github_token.opts.ignore_changes == ["value"]
    assert webhook_secret.opts.ignore_changes == ["value"]

    function = recorder.single("runnerFleetWebhook")
    variables = function.kwargs["environment"].kwargs["variables"]
    assert variables["ASG_NAME"] == "yoke-github-actions-runner-fleet"
    assert variables["WEBHOOK_SECRET_PARAMETER"] == (
        "/yoke/github-actions-runner-fleet/webhook-secret"
    )
    assert variables["REQUIRED_LABELS"] == (
        "self-hosted,Linux,ARM64,yoke-github-actions"
    )
    code_asset = function.kwargs["code"].kwargs["assets"]["index.py"]
    assert "X-Hub-Signature-256" in code_asset.kwargs["text"]
    assert "workflow_job" in code_asset.kwargs["text"]

    url = recorder.single("runnerFleetWebhookUrl")
    assert url.kwargs["authorization_type"] == "NONE"
    permission = recorder.single("runnerFleetWebhookUrlPermission")
    assert permission.kwargs["action"] == "lambda:InvokeFunctionUrl"
    assert permission.kwargs["principal"] == "*"
    assert permission.kwargs["function_url_auth_type"] == "NONE"
    invoke_permission = recorder.single("runnerFleetWebhookUrlInvokePermission")
    assert invoke_permission.props["function_name"].value == "runnerFleetWebhook.name"
    assert invoke_permission.props["region"] == "us-east-1"
    assert (
        invoke_permission.props["statement_id"]
        == "FunctionURLAllowPublicInvokeOnly"
    )
    assert permission in invoke_permission.opts.depends_on
    assert url in invoke_permission.opts.depends_on


def test_only_terminate_shutdown_mode_is_enabled_for_v1(monkeypatch):
    with pytest.raises(ValueError, match="shutdown_mode=terminate"):
        _runner_stack(monkeypatch, shutdown_mode="stop")
