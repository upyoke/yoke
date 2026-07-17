"""Tests for the GitHub Actions runner-fleet Pulumi template component."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import types

import pytest

from runtime.api.domain.test_webapp_registry_stack import (
    _Recorder,
    _load_template_module,
)
from runtime.api.domain.webapp_runner_fleet_test_support import _runner_stack


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
    subprocess.run(
        ["bash", "-n"], input=user_data, text=True, check=True,
        capture_output=True,
    )
    assert "RUNNER_COUNT=" not in user_data
    assert "RUNNER_ARCH=arm64" in user_data
    assert "awscli-exe-linux-${AWSCLI_ARCH}.zip" in user_data
    assert "AWSCLI_ARCH=\"aarch64\"" in user_data
    assert "actions/runners/downloads" not in user_data
    assert "github_broker bootstrap" in user_data
    assert "github_broker failed" in user_data
    assert "jq -cn" in user_data
    assert "{action:$action,instance_id:$instance_id}" in user_data
    assert '"action":"reap"' not in user_data
    assert "releases/latest" not in user_data
    assert "actions ALL=(ALL) NOPASSWD:ALL" in user_data
    assert "env HOME=/root PULUMI_HOME=/root/.pulumi" in user_data
    assert "PULUMI_BIN=/.pulumi/bin/pulumi" in user_data
    assert 'install -m 0755 "$PULUMI_BIN" /usr/bin/pulumi' in user_data
    assert "yoke-actions-runner.service" in user_data
    assert "initial-registration.json" in user_data
    assert "actions-runner.tar.gz" in user_data
    assert "svc.sh" not in user_data
    assert "trap bootstrap_failed ERR" in user_data
    assert "cleanup_bootstrap" in user_data
    assert user_data.index("cleanup_bootstrap\nsystemctl") < user_data.index(
        "enable --now yoke-actions-runner.service"
    )
    assert "set-desired-capacity" not in user_data
    assert "GITHUB_BROKER_FUNCTION=yoke-runner-fleet-token-broker" in user_data
    assert "GITHUB_WEB_URL=https://github.com" in user_data
    assert "/etc/yoke-runner-fleet.json" not in user_data
    assert "Environment=GITHUB_BROKER_FUNCTION" not in user_data
    assert "aws lambda invoke" in user_data
    assert "GITHUB_TOKEN" not in user_data
    assert "ssm get-parameter" not in user_data

def test_user_data_serializes_broker_actions_as_json(monkeypatch, tmp_path):
    recorder, _stack = _runner_stack(monkeypatch)
    launch_template = recorder.single("runnerFleetLaunchTemplate")
    user_data = base64.b64decode(
        launch_template.kwargs["user_data"],
    ).decode()
    function = user_data.split("github_broker() {", 1)[1].split(
        "\n\nBOOTSTRAP_FILE=", 1,
    )[0]
    aws_path = tmp_path / "aws"
    aws_path.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, pathlib, sys\n"
        "args = sys.argv[1:]\n"
        "payload = args[args.index('--payload') + 1]\n"
        "pathlib.Path(os.environ['PAYLOAD_PATH']).write_text(payload)\n"
        "pathlib.Path(os.environ['ARGS_PATH']).write_text(json.dumps(args))\n"
        "pathlib.Path(args[-1]).write_text('{}')\n"
        "print('None')\n"
    )
    aws_path.chmod(0o755)
    observed = []
    for action in ("bootstrap", "ready", "failed"):
        payload_path = tmp_path / f"{action}-payload.json"
        args_path = tmp_path / f"{action}-args.json"
        env = dict(os.environ)
        env["PATH"] = f"{tmp_path}:{env['PATH']}"
        env["PAYLOAD_PATH"] = str(payload_path)
        env["ARGS_PATH"] = str(args_path)
        subprocess.run(
            ["bash"],
            input=(
                "set -euo pipefail\n"
                "GITHUB_BROKER_FUNCTION=broker\n"
                "REGION=us-east-1\n"
                "INSTANCE_ID=i-0123456789abcdef0\n"
                f"github_broker() {{{function}\n"
                f"github_broker {action} >/dev/null\n"
            ),
            text=True,
            check=True,
            capture_output=True,
            env=env,
        )
        observed.append(json.loads(payload_path.read_text()))
        argv = json.loads(args_path.read_text())
        assert argv[argv.index("--cli-binary-format") + 1] == (
            "raw-in-base64-out"
        )

    assert observed == [
        {"action": action, "instance_id": "i-0123456789abcdef0"}
        for action in ("bootstrap", "ready", "failed")
    ]


def test_runner_network_is_dedicated_and_egress_limited(monkeypatch):
    recorder, _stack = _runner_stack(monkeypatch)
    vpc = recorder.single("runnerFleetVpc")
    assert vpc.kwargs["cidr_block"] == "10.253.0.0/24"
    subnet = recorder.single("runnerFleetSubnet")
    assert subnet.kwargs["vpc_id"].value == "runnerFleetVpc.id"
    assert subnet.kwargs["map_public_ip_on_launch"] is True
    asg = recorder.single("runnerFleetAsg")
    assert asg.kwargs["vpc_zone_identifiers"][0].value == (
        "runnerFleetSubnet.id"
    )
    security_group = recorder.single("runnerFleetSecurityGroup")
    egress = security_group.kwargs["egress"]
    assert {(rule.kwargs["protocol"], rule.kwargs["from_port"]) for rule in egress} == {
        ("tcp", 443), ("tcp", 80), ("udp", 53), ("tcp", 53),
        ("tcp", 22),
    }
    assert all(rule.kwargs["protocol"] != "-1" for rule in egress)
    ssh_rules = [rule for rule in egress if rule.kwargs["from_port"] == 22]
    assert [rule.kwargs["cidr_blocks"] for rule in ssh_rules] == [
        ["203.0.113.10/32"], ["203.0.113.11/32"],
    ]
    assert all(
        rule.kwargs["cidr_blocks"] != ["0.0.0.0/0"]
        for rule in ssh_rules
    )
    assert recorder.stack_references == ["yoke-prod", "yoke-stage"]
    assert recorder.stack_reference_outputs == [
        ("yoke-prod", "originElasticIpAddress"),
        ("yoke-stage", "originElasticIpAddress"),
    ]


def test_runner_network_omits_ssh_without_deployment_stacks(monkeypatch):
    recorder, _stack = _runner_stack(
        monkeypatch,
        config_overrides={"deployment_ssh_stack_outputs": {}},
        authority_overrides={"deployment_ssh_stack_outputs": {}},
    )
    egress = recorder.single("runnerFleetSecurityGroup").kwargs["egress"]

    assert all(rule.kwargs["from_port"] != 22 for rule in egress)
    assert not hasattr(recorder, "stack_references")


def test_runner_network_deduplicates_same_ssh_destination(monkeypatch):
    recorder, _stack = _runner_stack(
        monkeypatch,
        stack_reference_outputs={
            "yoke-prod": {"originElasticIpAddress": "203.0.113.10"},
            "yoke-stage": {"originElasticIpAddress": "203.0.113.10"},
        },
    )
    egress = recorder.single("runnerFleetSecurityGroup").kwargs["egress"]
    ssh_rules = [rule for rule in egress if rule.kwargs["from_port"] == 22]

    assert [rule.kwargs["cidr_blocks"] for rule in ssh_rules] == [
        ["203.0.113.10/32"],
    ]
    assert ssh_rules[0].kwargs["description"] == (
        "SSH to deployment stack yoke-prod"
    )
    assert recorder.stack_references == ["yoke-prod", "yoke-stage"]


def test_runner_network_rejects_non_ipv4_stack_output(monkeypatch):
    with pytest.raises(RuntimeError, match="must use an IPv4 Elastic IP"):
        _runner_stack(
            monkeypatch,
            stack_reference_outputs={
                "yoke-prod": {"originElasticIpAddress": "2001:db8::1"},
                "yoke-stage": {"originElasticIpAddress": "203.0.113.11"},
            },
        )


def test_idle_reaper_runs_outside_the_workflow_host(monkeypatch):
    recorder, _stack = _runner_stack(monkeypatch)

    reaper_runtime = recorder.single("runnerFleetGithubReaperRuntime")
    for parameter_name in (
        "runnerFleetLifecycleState",
        "runnerFleetQueueActivity",
        "runnerFleetRunnerProgress",
        "runnerFleetRunnerCompletion",
    ):
        assert recorder.single(parameter_name) in reaper_runtime.opts.depends_on
    schedule = recorder.single("runnerFleetIdleReaperSchedule")
    assert schedule.kwargs["schedule_expression"] == "rate(1 minute)"
    target = recorder.single("runnerFleetIdleReaperTarget")
    assert target.kwargs["input"] == '{"action":"reap"}'
    permission = recorder.single("runnerFleetIdleReaperInvoke")
    assert permission.kwargs["principal"] == "events.amazonaws.com"
    assert permission in target.opts.depends_on


def test_user_data_treats_rendered_values_as_data(monkeypatch):
    recorder = _Recorder()
    host_cycle = _load_template_module(
        monkeypatch, recorder, "webapp_runner_host_cycle.py",
    )
    internals = _load_template_module(
        monkeypatch, recorder, "webapp_runner_fleet_internals.py",
        extra_modules={"webapp_runner_host_cycle": host_cycle},
    )
    args = types.SimpleNamespace(
        deploy_namespace="yoke$(exit 77)",
        github_repo="acme/repo$(exit 78)",
        github_web_url="https://github.example.test$(exit 79)",
        runner_labels=["self-hosted", "label$(exit 80)"],
        runner_count=1,
        idle_shutdown_minutes=5,
        architecture="arm64",
    )
    encoded = internals._user_data(
        args=args,
        region="us-east-1",
        github_broker_function="broker$(exit 82)",
    )
    script = base64.b64decode(encoded).decode()
    assignments = script.split("\napt-get update", 1)[0]
    result = subprocess.run(
        ["bash"],
        input=assignments + '\nprintf "%s" "$PROJECT"',
        text=True,
        check=True,
        capture_output=True,
    )

    assert result.stdout == "yoke$(exit 77)"
    assert "instance_id" in script


def test_asg_starts_at_zero_and_keeps_one_disposable_host(monkeypatch):
    recorder, _stack = _runner_stack(monkeypatch)
    asg = recorder.single("runnerFleetAsg")

    assert asg.kwargs["name"] == "yoke-github-actions-runner-fleet"
    assert asg.kwargs["min_size"] == 0
    assert "desired_capacity" not in asg.kwargs
    assert asg.kwargs["max_size"] == 1
    assert asg.kwargs["vpc_zone_identifiers"][0].value == (
        "runnerFleetSubnet.id"
    )
    assert asg.opts.ignore_changes == ["desiredCapacity"]


def test_asg_supports_multiple_isolated_ephemeral_hosts(monkeypatch):
    recorder, _stack = _runner_stack(
        monkeypatch, runner_count=2, max_count=2,
    )

    assert recorder.single("runnerFleetAsg").kwargs["max_size"] == 2
    webhook = recorder.single("runnerFleetWebhook")
    assert webhook.kwargs["environment"].kwargs["variables"][
        "DESIRED_RUNNER_COUNT"
    ] == "2"
    reaper = recorder.single("runnerFleetGithubReaper")
    assert reaper.kwargs["environment"].kwargs["variables"][
        "DESIRED_RUNNER_COUNT"
    ] == "2"


def test_stack_rejects_desired_capacity_above_maximum(monkeypatch):
    with pytest.raises(ValueError, match="greater than or equal"):
        _runner_stack(monkeypatch, runner_count=2, max_count=1)


def test_webhook_lambda_is_hmac_backed_and_routes_matching_labels(monkeypatch):
    recorder, _stack = _runner_stack(monkeypatch)

    generated_secret = recorder.single("runnerFleetWebhookSecretValue")
    assert generated_secret.kwargs["length"] == 64
    assert generated_secret.kwargs["special"] is False
    webhook_secret = recorder.single("runnerFleetWebhookSecret")
    assert webhook_secret.kwargs["type"] == "SecureString"
    assert webhook_secret.kwargs["value"].value == (
        "runnerFleetWebhookSecretValue.result"
    )
    assert webhook_secret.opts.ignore_changes is None

    function = recorder.single("runnerFleetWebhook")
    variables = function.kwargs["environment"].kwargs["variables"]
    assert variables["ASG_NAME"] == "yoke-github-actions-runner-fleet"
    assert variables["WEBHOOK_SECRET_PARAMETER"] == (
        "/yoke/github-actions-runner-fleet/webhook-secret"
    )
    assert variables["WEBHOOK_SECRET_VERSION"] == (
        "runnerFleetWebhookSecret.version"
    )
    assert variables["REQUIRED_LABELS"] == (
        "self-hosted,Linux,ARM64,yoke-github-actions"
    )
    assert variables["EXPECTED_REPOSITORY_ID"] == "789012"
    assert variables["EXPECTED_REPOSITORY"] == "upyoke/yoke"
    assert variables["DESIRED_RUNNER_COUNT"] == "1"
    assert variables["QUEUE_ACTIVITY_PARAMETER"] == (
        "/yoke/github-actions-runner-fleet/queue-activity"
    )
    assert variables["RUNNER_PROGRESS_PARAMETER"] == (
        "/yoke/github-actions-runner-fleet/runner-progress"
    )
    assert variables["RUNNER_COMPLETION_PARAMETER"] == (
        "/yoke/github-actions-runner-fleet/runner-completion"
    )
    code_asset = function.kwargs["code"].kwargs["assets"]["index.py"]
    assert "X-Hub-Signature-256" in code_asset.kwargs["text"]
    assert "workflow_job" in code_asset.kwargs["text"]
    assert "_webhook_secret_cache" in code_asset.kwargs["text"]
    assert "wrong_repository" in code_asset.kwargs["text"]
    assert "QUEUE_ACTIVITY_PARAMETER" in code_asset.kwargs["text"]
    assert "RUNNER_PROGRESS_PARAMETER" in code_asset.kwargs["text"]
    assert "RUNNER_COMPLETION_PARAMETER" in code_asset.kwargs["text"]
    assert 'DesiredCapacity=int(os.environ["DESIRED_RUNNER_COUNT"])' in (
        code_asset.kwargs["text"]
    )
    assert code_asset.kwargs["text"].index("QUEUE_ACTIVITY_PARAMETER") < (
        code_asset.kwargs["text"].index("set_desired_capacity")
    )
    assert function.kwargs["reserved_concurrent_executions"] == 5

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
