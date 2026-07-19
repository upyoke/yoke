"""Security boundaries for the rendered GitHub Actions runner fleet."""

import json
from pathlib import Path

from runtime.api.domain.webapp_runner_fleet_test_support import _runner_stack
from runtime.api.domain.webapp_pulumi_test_support import _pack_program_source
from yoke_core.domain.project_renderer_pulumi_files import (
    RUNNER_FLEET_PROGRAM_FILES,
)


def test_github_broker_is_only_app_key_reader_and_token_minter(monkeypatch):
    recorder, stack = _runner_stack(monkeypatch)

    broker = recorder.single("runnerFleetGithubBroker")
    assert broker.kwargs["runtime"] == "nodejs22.x"
    assert broker.kwargs["handler"] == "index.handler"
    assert broker.kwargs["name"] == "yoke-runner-fleet-token-broker"
    variables = broker.kwargs["environment"].kwargs["variables"]
    assert variables["GITHUB_INSTALLATION_ID"] == "123456"
    assert variables["GITHUB_REPOSITORY_ID"] == "789012"
    assert variables["GITHUB_REPO_OWNER"] == "upyoke"
    assert variables["GITHUB_REPO_NAME"] == "yoke"
    source = broker.kwargs["code"].kwargs["assets"]["index.mjs"].kwargs["text"]
    api_source = broker.kwargs["code"].kwargs["assets"][
        "webapp_runner_github_api.mjs"
    ].kwargs["text"]
    registration_source = broker.kwargs["code"].kwargs["assets"][
        "webapp_runner_registration.mjs"
    ].kwargs["text"]
    aws_state_source = broker.kwargs["code"].kwargs["assets"][
        "webapp_runner_aws_state.mjs"
    ].kwargs["text"]
    termination_source = broker.kwargs["code"].kwargs["assets"][
        "webapp_runner_termination.mjs"
    ].kwargs["text"]
    assert 'administration: "write"' in api_source
    assert 'repository_hooks: "read"' in api_source
    assert 'actions_variables: "read"' in api_source
    assert "repository_ids" in api_source
    assert 'brokerMode === "bootstrap"' in source
    assert 'brokerMode === "reaper"' in source
    assert "runnerDownloadUrl()" in registration_source
    assert "runner bootstrap was already consumed" in registration_source
    assert "registerRunner" in registration_source
    assert "currentAsgInstanceIds" in aws_state_source
    assert "MaxRecords: 50" in aws_state_source
    assert "termination_acknowledged" in termination_source
    assert "redirect: \"error\"" in api_source
    assert "validatedApiBase" in api_source
    assert "canonical GitHub HTTPS API base" in api_source
    assert "SecretString" in api_source
    assert variables["BROKER_MODE"] == "bootstrap"
    reaper = recorder.single("runnerFleetGithubReaper")
    assert reaper.kwargs["runtime"] == "nodejs22.x"
    assert reaper.kwargs["environment"].kwargs["variables"]["BROKER_MODE"] == (
        "reaper"
    )

    secret_policy = recorder.single("runnerFleetGithubBootstrapSecretRead")
    assert "secretsmanager:GetSecretValue" in secret_policy.kwargs["policy"]
    ci_invoke = recorder.single("runnerFleetGithubBrokerInvoke")
    assert ci_invoke.kwargs["role"] == "yoke-ci-github"
    assert "lambda:InvokeFunction" in ci_invoke.kwargs["policy"]
    assert "runnerFleetGithubBroker.arn" in ci_invoke.kwargs["policy"]
    assert "secretsmanager" not in ci_invoke.kwargs["policy"]
    invoke_policy = recorder.single("runnerFleetInstanceRuntime")
    assert "lambda:InvokeFunction" in invoke_policy.kwargs["policy"]
    assert "secretsmanager" not in invoke_policy.kwargs["policy"]
    assert "runnerFleetGithubBroker" in invoke_policy.kwargs["policy"]
    assert "autoscaling:SetDesiredCapacity" not in invoke_policy.kwargs["policy"]
    bootstrap_policy = recorder.single("runnerFleetGithubBootstrapRuntime")
    assert "autoscaling:SetDesiredCapacity" not in bootstrap_policy.kwargs["policy"]
    assert "ssm:GetParametersByPath" not in bootstrap_policy.kwargs["policy"]
    assert "/bootstrap/*" in bootstrap_policy.kwargs["policy"]
    reaper_policy = recorder.single("runnerFleetGithubReaperRuntime")
    reaper_document = json.loads(reaper_policy.kwargs["policy"])
    assert "autoscaling:SetDesiredCapacity" in reaper_policy.kwargs["policy"]
    assert "autoscaling:TerminateInstanceInAutoScalingGroup" in (
        reaper_policy.kwargs["policy"]
    )
    assert "ec2:DescribeInstances" in reaper_policy.kwargs["policy"]
    path_read = next(
        statement for statement in reaper_document["Statement"]
        if statement["Action"] == "ssm:GetParametersByPath"
    )
    marker_delete = next(
        statement for statement in reaper_document["Statement"]
        if "ssm:DeleteParameter" in statement["Action"]
    )
    assert path_read["Resource"].endswith("/bootstrap")
    assert set(marker_delete["Action"]) == {
        "ssm:PutParameter", "ssm:DeleteParameter",
    }
    assert marker_delete["Resource"].endswith("/bootstrap/*")
    for resource_name in (
        "runnerFleetLifecycleState.arn",
        "runnerFleetQueueActivity.arn",
        "runnerFleetRunnerProgress.arn",
        "runnerFleetRunnerCompletion.arn",
    ):
        assert resource_name in reaper_policy.kwargs["policy"]
    webhook_policy = recorder.single("runnerFleetWebhookRuntime")
    for resource_name in (
        "runnerFleetWebhookSecret.arn",
        "runnerFleetQueueActivity.arn",
        "runnerFleetRunnerProgress.arn",
        "runnerFleetRunnerCompletion.arn",
        "runnerFleetAsg.arn",
    ):
        assert resource_name in webhook_policy.kwargs["policy"]
    assert '"Resource": "*"' not in webhook_policy.kwargs["policy"]
    role_policies = [
        resource for resource in recorder.resources
        if resource.resource_type == "aws:iam:RolePolicy"
    ]
    wildcard_policies = [
        policy for policy in role_policies
        if '"Resource": "*"' in policy.kwargs["policy"]
    ]
    assert wildcard_policies == [bootstrap_policy, reaper_policy]
    assert not any(
        resource.resource_name == "runnerFleetSsmManagedInstanceCore"
        for resource in recorder.resources
    )
    assert stack.registered_outputs["runnerFleetWebhookEvent"] == "workflow_job"


def test_runner_fleet_has_only_short_lived_repository_credential_input():
    stack_source = _pack_program_source("webapp_runner_fleet_stack.py").read_text()
    webhook_source = _pack_program_source(
        "webapp_runner_github_webhook.py"
    ).read_text()
    provider_source = _pack_program_source(
        "webapp_github_repository_provider.py"
    ).read_text()
    runtime_sources = "\n".join(
        _pack_program_source(name).read_text()
        for name in RUNNER_FLEET_PROGRAM_FILES
        if name not in {
            "webapp_runner_fleet_stack.py",
            "webapp_runner_github_webhook.py",
        }
    )
    requirements = _pack_program_source("requirements.txt").read_text()
    operations = Path(__file__).resolve().parents[3].joinpath(
        "packs", "self-hosted-runners", "versions", "1.0.0", "files",
        "docs", "packs", "self-hosted-runners", "operations.md",
    ).read_text()

    assert "require_repository_token_environment" in stack_source
    assert "RUNNER_FLEET_GITHUB_TOKEN" in provider_source
    assert "create_repository_provider" in webhook_source
    assert 'os.environ.get(GITHUB_TOKEN_ENV' in provider_source
    assert "hmac.compare_digest(token, provider_token)" in provider_source
    assert "os.environ.pop(GITHUB_TOKEN_ENV)" in provider_source
    assert "os.environ[GITHUB_TOKEN_ENV] = provider_token" in provider_source
    assert "token=provider_token" not in provider_source
    assert "RUNNER_FLEET_GITHUB_TOKEN" not in runtime_sources
    sources = stack_source + webhook_source + provider_source + runtime_sources
    assert "GITHUB_TOKEN_PARAMETER" not in sources
    assert "/github-token" not in sources
    assert "pulumi-github" in requirements
    assert "pulumi-random" in requirements
    assert "repository_hooks: write" in operations
    assert "actions_variables: write" in operations
    assert "runnerFleetRoutingVariable" in operations
    assert "Arm and disarm only through the capability plus runner-fleet apply" in operations
    assert "variable writes are drift" in operations
    assert "network.deployment_ssh_stack_names" in operations
    assert "originElasticIpAddress" in operations
    assert "vpsElasticIpAddress" in operations
    assert "Literal addresses and CIDRs are not" in operations
    assert "Pulumi.StackReference" in operations
    assert "configure one manual GitHub webhook" not in operations


def test_runner_variable_adoption_docs_preserve_generated_pulumi_identity():
    root = Path(__file__).resolve().parents[3]
    documents = (
        (root / "docs" / "github-app-operations.md").read_text(),
        root.joinpath(
            "packs", "self-hosted-runners", "versions", "1.0.0", "files",
            "docs", "packs", "self-hosted-runners", "operations.md",
        ).read_text(),
    )

    for document in documents:
        assert "--import-file <preview-import-file.json>" in document
        assert "--file <runner-variable-import-file.json>" in document
        assert "preserve its generated `parent`" in document
        assert "`provider` fields unchanged" in document
        assert "positional" in document
        assert "final zero-change refresh" in document


def test_runner_network_derives_standalone_ssh_target_from_stack_output(
    monkeypatch,
):
    stack_outputs = {"yoke-platform-vps": "vpsElasticIpAddress"}
    recorder, _stack = _runner_stack(
        monkeypatch,
        config_overrides={"deployment_ssh_stack_outputs": stack_outputs},
        authority_overrides={"deployment_ssh_stack_outputs": stack_outputs},
        stack_reference_outputs={
            "yoke-platform-vps": {
                "vpsElasticIpAddress": "198.51.100.42",
            },
        },
    )
    egress = recorder.single("runnerFleetSecurityGroup").kwargs["egress"]
    ssh_rules = [rule for rule in egress if rule.kwargs["from_port"] == 22]

    assert [rule.kwargs["cidr_blocks"] for rule in ssh_rules] == [
        ["198.51.100.42/32"],
    ]
    assert recorder.stack_references == ["yoke-platform-vps"]
    assert recorder.stack_reference_outputs == [
        ("yoke-platform-vps", "vpsElasticIpAddress"),
    ]
