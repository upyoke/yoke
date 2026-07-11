"""Security boundaries for the rendered GitHub Actions runner fleet."""

from pathlib import Path

import pytest

from runtime.api.domain.test_webapp_registry_stack import _Recorder
from runtime.api.domain.webapp_runner_fleet_test_support import _runner_stack


def test_github_broker_is_only_app_key_reader_and_token_minter(monkeypatch):
    recorder, stack = _runner_stack(monkeypatch)

    broker = recorder.single("runnerFleetGithubBroker")
    assert broker.kwargs["runtime"] == "nodejs22.x"
    assert broker.kwargs["handler"] == "index.handler"
    variables = broker.kwargs["environment"].kwargs["variables"]
    assert variables["GITHUB_INSTALLATION_ID"] == "123456"
    assert variables["GITHUB_REPOSITORY_ID"] == "789012"
    assert variables["GITHUB_REPO_OWNER"] == "upyoke"
    assert variables["GITHUB_REPO_NAME"] == "yoke"
    source = broker.kwargs["code"].kwargs["assets"]["index.mjs"].kwargs["text"]
    api_source = broker.kwargs["code"].kwargs["assets"][
        "webapp_runner_github_api.mjs"
    ].kwargs["text"]
    aws_state_source = broker.kwargs["code"].kwargs["assets"][
        "webapp_runner_aws_state.mjs"
    ].kwargs["text"]
    termination_source = broker.kwargs["code"].kwargs["assets"][
        "webapp_runner_termination.mjs"
    ].kwargs["text"]
    assert 'permissions":{"administration":"write"}' in api_source
    assert "repository_hooks" not in api_source
    assert "actions_variables" not in api_source
    assert "repository_ids" in api_source
    assert 'brokerMode === "bootstrap"' in source
    assert 'brokerMode === "reaper"' in source
    assert "runnerDownloadUrl()" in source
    assert "runner bootstrap was already consumed" in source
    assert "currentAsgInstanceIds" in aws_state_source
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
    assert "autoscaling:SetDesiredCapacity" in reaper_policy.kwargs["policy"]
    assert "autoscaling:TerminateInstanceInAutoScalingGroup" in (
        reaper_policy.kwargs["policy"]
    )
    assert "ec2:DescribeInstances" in reaper_policy.kwargs["policy"]
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
    root = Path(__file__).resolve().parents[3] / "templates" / "webapp" / "infra"
    stack_source = (root / "webapp_runner_fleet_stack.py").read_text()
    webhook_source = (root / "webapp_runner_github_webhook.py").read_text()
    provider_source = (
        root / "webapp_github_repository_provider.py"
    ).read_text()
    runtime_sources = "\n".join(
        path.read_text()
        for path in root.glob("webapp_runner_*")
        if path.name not in {
            "webapp_runner_fleet_stack.py",
            "webapp_runner_github_webhook.py",
        }
    )
    requirements = (root / "requirements.txt").read_text()
    readme = root.parent / "README.md"
    readme_text = readme.read_text()

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
    assert "repository_hooks: write" in readme_text
    assert "actions_variables: write" in readme_text
    assert "runnerFleetRoutingVariable" in readme_text
    assert "direct variable" in readme_text
    assert "writes are drift" in readme_text
    assert "configure one manual GitHub webhook" not in readme_text


def test_runner_variable_adoption_docs_preserve_generated_pulumi_identity():
    root = Path(__file__).resolve().parents[3]
    documents = (
        (root / "docs" / "github-app-operations.md").read_text(),
        (root / "templates" / "webapp" / "RUNNER-FLEET.md").read_text(),
    )

    for document in documents:
        assert "--import-file <preview-import-file.json>" in document
        assert "--file <runner-variable-import-file.json>" in document
        assert "preserve its generated `parent`" in document
        assert "`provider` fields unchanged" in document
        assert "positional" in document
        assert "final zero-change refresh" in document


@pytest.mark.parametrize(
    ("config_overrides", "authority_overrides", "field"),
    [
        (
            {"github_api_url": "http://github.internal.example/api/v3"},
            {"api_url": "https://github.internal.example/api/v3"},
            "api_url",
        ),
        (
            {"github_api_url": "https://attacker.example/api/v3"},
            {"api_url": "https://api.github.com"},
            "api_url",
        ),
        (
            {
                "github_app_issuer": "Iv1.other",
                "github_installation_id": "999",
                "github_repository_id": "998",
            },
            {
                "app_issuer": "Iv1.runner-fleet",
                "installation_id": "123456",
                "repository_id": "789012",
            },
            "app_issuer",
        ),
        (
            {
                "github_capability": "other",
                "github_app_environment": "other-stage",
                "github_repo_owner": "other-org",
                "github_repo_name": "other-repo",
                "github_private_key_secret_arn": (
                    "arn:aws:secretsmanager:us-east-1:123456789012:"
                    "secret:other-app"
                ),
            },
            {
                "github_capability": "github",
                "github_app_environment": "yoke-api-stage",
                "repo_owner": "upyoke",
                "repo_name": "yoke",
                "private_key_secret_arn": (
                    "arn:aws:secretsmanager:us-east-1:123456789012:"
                    "secret:yoke-github-app-AbCdEf"
                ),
            },
            "github_capability",
        ),
        (
            {
                "runner_variable_name": "OTHER_ROUTE",
                "runner_labels": ["self-hosted", "Linux", "X64"],
                "routing_enabled": False,
            },
            {
                "runner_variable_name": "YOKE_LINUX_RUNS_ON",
                "runner_labels": [
                    "self-hosted", "Linux", "ARM64",
                    "yoke-github-actions",
                ],
                "routing_enabled": True,
            },
            "runner_labels",
        ),
        (
            {
                "aws_capability": "other-admin",
                "aws_region": "us-west-2",
                "instance_type": "c7i.16xlarge",
                "architecture": "x64",
                "root_volume_gb": 1000,
                "runner_count": 2,
                "max_runner_count": 2,
                "idle_shutdown_minutes": 5,
                "shutdown_mode": "stop",
            },
            {
                "aws_capability": "aws-admin",
                "aws_region": "us-east-1",
                "instance_type": "m7g.2xlarge",
                "architecture": "arm64",
                "root_volume_gb": 100,
                "runner_count": 1,
                "max_runner_count": 1,
                "idle_shutdown_minutes": 30,
                "shutdown_mode": "terminate",
            },
            "aws_region",
        ),
    ],
)
def test_authority_drift_refuses_before_github_provider_construction(
    monkeypatch, config_overrides, authority_overrides, field,
):
    recorder = _Recorder()

    with pytest.raises(RuntimeError, match=field):
        _runner_stack(
            monkeypatch,
            config_overrides=config_overrides,
            authority_overrides=authority_overrides,
            recorder=recorder,
        )

    assert recorder.resources == []


def test_wrong_pulumi_stack_refuses_before_resource_construction(monkeypatch):
    recorder = _Recorder()

    with pytest.raises(RuntimeError, match="stack_name"):
        _runner_stack(
            monkeypatch,
            stack_name="wrong-runner-state",
            authority_overrides={"stack_name": "yoke-runner-fleet"},
            recorder=recorder,
        )

    assert recorder.resources == []
