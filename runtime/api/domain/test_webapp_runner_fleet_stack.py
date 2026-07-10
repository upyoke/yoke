"""Tests for the GitHub Actions runner-fleet Pulumi template component."""

from __future__ import annotations

import base64
import os
import subprocess
import types

import pytest

from runtime.api.domain.test_webapp_registry_stack import (
    _Recorder,
    _load_template_module,
    _make_resource_class,
)

_WEBHOOK_TOKEN = "github_pat_short_lived_webhook_test"


def _runner_stack(
    monkeypatch, *, shutdown_mode="terminate", runner_count=1, max_count=1,
    webhook_token=_WEBHOOK_TOKEN,
    github_provider_token=_WEBHOOK_TOKEN,
    github_api_url="https://api.github.com",
    github_web_url="https://github.com",
):
    recorder = _Recorder()
    if webhook_token is None:
        monkeypatch.delenv("RUNNER_FLEET_WEBHOOK_TOKEN", raising=False)
    else:
        monkeypatch.setenv("RUNNER_FLEET_WEBHOOK_TOKEN", webhook_token)
    if github_provider_token is None:
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    else:
        monkeypatch.setenv("GITHUB_TOKEN", github_provider_token)
    # The stack module imports its internals sibling at top level; the
    # template infra dir is not on sys.path under file-location loading, so
    # load the internals module against the same recorder and inject it under
    # its bare runtime name before the stack import runs.
    internals = _load_template_module(
        monkeypatch, recorder, "webapp_runner_fleet_internals.py",
    )
    github_state = _load_template_module(
        monkeypatch, recorder, "webapp_runner_github_state.py",
    )
    broker_stack = _load_template_module(
        monkeypatch, recorder, "webapp_runner_github_broker_stack.py",
        extra_modules={"webapp_runner_github_state": github_state},
    )
    iam = _load_template_module(
        monkeypatch, recorder, "webapp_runner_fleet_iam.py",
        extra_modules={"webapp_runner_fleet_internals": internals},
    )
    network = _load_template_module(
        monkeypatch, recorder, "webapp_runner_fleet_network.py",
    )
    pulumi_random = types.ModuleType("pulumi_random")
    pulumi_random.RandomPassword = _make_resource_class(
        recorder, "random:index:RandomPassword",
    )
    pulumi_github = types.ModuleType("pulumi_github")
    provider_class = _make_resource_class(
        recorder, "pulumi:providers:github",
    )

    class _EnvReadingProvider(provider_class):
        def __init__(self, resource_name, opts=None, **kwargs):
            ambient_token = os.environ.get("GITHUB_TOKEN")
            if ambient_token is not None:
                kwargs["token"] = ambient_token
            super().__init__(resource_name, opts=opts, **kwargs)
            self.constructor_github_token = ambient_token

    pulumi_github.Provider = _EnvReadingProvider
    pulumi_github.RepositoryWebhook = _make_resource_class(
        recorder, "github:index/repositoryWebhook:RepositoryWebhook",
    )
    github_webhook = _load_template_module(
        monkeypatch, recorder, "webapp_runner_github_webhook.py",
        extra_modules={"pulumi_github": pulumi_github},
    )
    module = _load_template_module(
        monkeypatch, recorder, "webapp_runner_fleet_stack.py",
        extra_modules={
            "webapp_runner_fleet_internals": internals,
            "webapp_runner_fleet_iam": iam,
            "webapp_runner_fleet_network": network,
            "webapp_runner_github_broker_stack": broker_stack,
            "webapp_runner_github_webhook": github_webhook,
            "pulumi_random": pulumi_random,
        },
    )
    stack = module.WebappRunnerFleetStack(
        "yoke-runner-fleet",
        module.WebappRunnerFleetArgs(
            deploy_namespace="yoke",
            github_repo="upyoke/yoke",
            github_repo_owner="upyoke",
            github_repo_name="yoke",
            github_installation_id="123456",
            github_repository_id="789012",
            github_app_issuer="Iv1.runner-fleet",
            github_api_url=github_api_url,
            github_web_url=github_web_url,
            github_private_key_secret_arn=(
                "arn:aws:secretsmanager:us-east-1:123456789012:"
                "secret:yoke-github-app-AbCdEf"
            ),
            runner_labels=[
                "self-hosted", "Linux", "ARM64", "yoke-github-actions",
            ],
            runner_count=runner_count,
            max_runner_count=max_count,
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
    subprocess.run(
        ["bash", "-n"], input=user_data, text=True, check=True,
        capture_output=True,
    )
    assert "RUNNER_COUNT=" not in user_data
    assert "RUNNER_ARCH=arm64" in user_data
    assert "awscli-exe-linux-${AWSCLI_ARCH}.zip" in user_data
    assert "AWSCLI_ARCH=\"aarch64\"" in user_data
    assert "actions/runners/downloads" not in user_data
    assert '\"action\":\"bootstrap\"' in user_data
    assert user_data.count('"action":"bootstrap"') == 1
    assert user_data.count('"action":"ready"') == 1
    assert user_data.count('"action":"failed"') == 1
    assert '"action":"reap"' not in user_data
    assert ".registration_token // empty" in user_data
    assert "releases/latest" not in user_data
    assert "actions ALL=(ALL) NOPASSWD:ALL" in user_data
    assert "env HOME=/root PULUMI_HOME=/root/.pulumi" in user_data
    assert "PULUMI_BIN=/.pulumi/bin/pulumi" in user_data
    assert 'install -m 0755 "$PULUMI_BIN" /usr/bin/pulumi' in user_data
    assert '(cd "${dir}" && ./svc.sh install actions && ./svc.sh start)' in user_data
    assert "--ephemeral" in user_data
    assert "trap bootstrap_failed ERR" in user_data
    assert "cleanup_bootstrap" in user_data
    assert user_data.index("cleanup_bootstrap\ngithub_broker") < user_data.index(
        "./svc.sh start"
    )
    assert "set-desired-capacity" not in user_data
    assert "GITHUB_BROKER_FUNCTION=runnerFleetGithubBroker.name" in user_data
    assert "GITHUB_WEB_URL=https://github.com" in user_data
    assert "sudo -u actions bash -c" in user_data
    assert '--url "$2" --token "$3" --name "$4" --labels "$5"' in user_data
    assert "/etc/yoke-runner-fleet.json" not in user_data
    assert "Environment=GITHUB_BROKER_FUNCTION" not in user_data
    assert "aws lambda invoke" in user_data
    assert "GITHUB_TOKEN" not in user_data
    assert "ssm get-parameter" not in user_data


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
    }
    assert all(rule.kwargs["protocol"] != "-1" for rule in egress)


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
    internals = _load_template_module(
        monkeypatch, recorder, "webapp_runner_fleet_internals.py",
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
    assert "sudo -u actions bash -c" in script
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


def test_stack_rejects_shared_root_capable_runner_hosts(monkeypatch):
    with pytest.raises(ValueError, match="one ephemeral runner per host"):
        _runner_stack(monkeypatch, runner_count=2, max_count=2)


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
