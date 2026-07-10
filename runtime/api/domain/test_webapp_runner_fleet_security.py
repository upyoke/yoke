"""Security boundaries for the rendered GitHub Actions runner fleet."""

from pathlib import Path

from runtime.api.domain.test_webapp_runner_fleet_stack import _runner_stack


def test_github_broker_is_only_app_key_reader_and_token_minter(monkeypatch):
    recorder, stack = _runner_stack(monkeypatch)

    broker = recorder.single("runnerFleetGithubBroker")
    assert broker.kwargs["runtime"] == "nodejs24.x"
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


def test_runner_fleet_has_no_long_lived_github_credential_inputs():
    root = Path(__file__).resolve().parents[3] / "templates" / "webapp" / "infra"
    sources = "\n".join(
        path.read_text() for path in root.glob("webapp_runner_*")
    )
    requirements = (root / "requirements.txt").read_text()

    assert "RUNNER_FLEET_WEBHOOK_TOKEN" not in sources
    assert "GITHUB_TOKEN_PARAMETER" not in sources
    assert "/github-token" not in sources
    assert "pulumi-github" not in requirements
    assert "pulumi-random" in requirements
