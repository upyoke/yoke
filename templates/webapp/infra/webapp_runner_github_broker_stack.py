# AUTO-GENERATED template source: templates/webapp/infra/webapp_runner_github_broker_stack.py. Do not hand-edit rendered copies; refresh through Yoke template/onboarding surfaces.
"""AWS resources for instance bootstrap and external runner lifecycle control."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Mapping

import pulumi
import pulumi_aws as aws

from webapp_runner_github_state import create_runner_github_state


RUNNER_GITHUB_LAMBDA_RUNTIME = "nodejs22.x"

if TYPE_CHECKING:
    from webapp_runner_fleet_config import WebappRunnerFleetArgs


@dataclass(frozen=True)
class RunnerGithubBrokerResources:
    """Bootstrap function plus lifecycle coordination parameters."""

    bootstrap_function: aws.lambda_.Function
    queue_activity_parameter: aws.ssm.Parameter
    runner_progress_parameter: aws.ssm.Parameter
    runner_completion_parameter: aws.ssm.Parameter


def _assume_role_policy(service: str) -> str:
    return json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": service},
            "Action": "sts:AssumeRole",
        }],
    })


def _policy(statements: list[dict]) -> str:
    return json.dumps({"Version": "2012-10-17", "Statement": statements})


def _create_lambda_role(
    resource_prefix: str,
    *,
    private_key_secret_arn: str,
    tags: Mapping[str, str],
    child_opts: pulumi.ResourceOptions,
) -> tuple[aws.iam.Role, aws.iam.RolePolicy]:
    role = aws.iam.Role(
        f"{resource_prefix}Role",
        assume_role_policy=_assume_role_policy("lambda.amazonaws.com"),
        tags=dict(tags),
        opts=child_opts,
    )
    aws.iam.RolePolicyAttachment(
        f"{resource_prefix}Logs",
        role=role.name,
        policy_arn=(
            "arn:aws:iam::aws:policy/service-role/"
            "AWSLambdaBasicExecutionRole"
        ),
        opts=child_opts,
    )
    secret_policy = aws.iam.RolePolicy(
        f"{resource_prefix}SecretRead",
        role=role.id,
        policy=_policy([{
            "Effect": "Allow",
            "Action": "secretsmanager:GetSecretValue",
            "Resource": private_key_secret_arn,
        }]),
        opts=child_opts,
    )
    return role, secret_policy


def _common_environment(
    args: WebappRunnerFleetArgs,
    *,
    asg_name: str,
    lifecycle_state_name: pulumi.Input[str],
    queue_activity_name: pulumi.Input[str],
    runner_progress_name: pulumi.Input[str],
    runner_completion_name: pulumi.Input[str],
    bootstrap_prefix: str,
) -> dict[str, pulumi.Input[str]]:
    return {
        "GITHUB_API_URL": args.github_api_url,
        "GITHUB_APP_ISSUER": args.github_app_issuer,
        "GITHUB_INSTALLATION_ID": args.github_installation_id,
        "GITHUB_REPOSITORY_ID": args.github_repository_id,
        "GITHUB_REPO_OWNER": args.github_repo_owner,
        "GITHUB_REPO_NAME": args.github_repo_name,
        "GITHUB_PRIVATE_KEY_SECRET_ARN": args.github_private_key_secret_arn,
        "RUNNER_ASG_NAME": asg_name,
        "RUNNER_ARCHITECTURE": (
            "arm64" if args.architecture.lower() == "arm64" else "x64"
        ),
        "RUNNER_PREFIX": f"{args.deploy_namespace}-github-actions-",
        "RUNNER_LABELS": ",".join(args.runner_labels),
        "IDLE_MINUTES": str(args.idle_shutdown_minutes),
        "LIFECYCLE_STATE_PARAMETER": lifecycle_state_name,
        "QUEUE_ACTIVITY_PARAMETER": queue_activity_name,
        "RUNNER_PROGRESS_PARAMETER": runner_progress_name,
        "RUNNER_COMPLETION_PARAMETER": runner_completion_name,
        "BOOTSTRAP_MARKER_PREFIX": bootstrap_prefix,
        "BOOTSTRAP_TIMEOUT_MINUTES": "30",
        "READY_GRACE_MINUTES": "5",
        "MAX_BOOTSTRAP_RETRIES": "3",
        "JOB_EVENT_TIMEOUT_MINUTES": "360",
    }


def _lambda_code() -> pulumi.AssetArchive:
    root = Path(__file__).parent
    return pulumi.AssetArchive({
        "index.mjs": pulumi.StringAsset(
            (root / "webapp_runner_github_broker.mjs").read_text()
        ),
        "webapp_runner_aws_state.mjs": pulumi.StringAsset(
            (root / "webapp_runner_aws_state.mjs").read_text()
        ),
        "webapp_runner_github_api.mjs": pulumi.StringAsset(
            (root / "webapp_runner_github_api.mjs").read_text()
        ),
        "webapp_runner_termination.mjs": pulumi.StringAsset(
            (root / "webapp_runner_termination.mjs").read_text()
        ),
    })


def create_runner_github_broker(
    args: WebappRunnerFleetArgs,
    *,
    region: str,
    asg_name: str,
    parameter_prefix: str,
    tags: Mapping[str, str],
    child_opts: pulumi.ResourceOptions,
) -> RunnerGithubBrokerResources:
    """Create one-time instance bootstrap and separately scheduled reaping."""
    bootstrap_prefix = f"{parameter_prefix}/bootstrap"
    state = create_runner_github_state(
        parameter_prefix,
        tags=tags,
        child_opts=child_opts,
    )
    account_id = aws.get_caller_identity().account_id
    bootstrap_arn = (
        f"arn:aws:ssm:{region}:{account_id}:"
        f"parameter{bootstrap_prefix}/*"
    )
    asg_arn = (
        f"arn:aws:autoscaling:{region}:{account_id}:autoScalingGroup:*:"
        f"autoScalingGroupName/{asg_name}"
    )

    bootstrap_role, bootstrap_secret = _create_lambda_role(
        "runnerFleetGithubBootstrap",
        private_key_secret_arn=args.github_private_key_secret_arn,
        tags=tags,
        child_opts=child_opts,
    )
    bootstrap_runtime = aws.iam.RolePolicy(
        "runnerFleetGithubBootstrapRuntime",
        role=bootstrap_role.id,
        policy=_policy([
            {
                "Effect": "Allow",
                "Action": ["ssm:GetParameter", "ssm:PutParameter"],
                "Resource": bootstrap_arn,
            },
            {
                "Effect": "Allow",
                "Action": "autoscaling:DescribeAutoScalingInstances",
                "Resource": "*",
            },
        ]),
        opts=child_opts,
    )
    common_environment = _common_environment(
        args,
        asg_name=asg_name,
        lifecycle_state_name=state.lifecycle_state.name,
        queue_activity_name=state.queue_activity.name,
        runner_progress_name=state.runner_progress.name,
        runner_completion_name=state.runner_completion.name,
        bootstrap_prefix=bootstrap_prefix,
    )
    bootstrap_function = aws.lambda_.Function(
        "runnerFleetGithubBroker",
        role=bootstrap_role.arn,
        runtime=RUNNER_GITHUB_LAMBDA_RUNTIME,
        handler="index.handler",
        timeout=60,
        reserved_concurrent_executions=2,
        code=_lambda_code(),
        environment=aws.lambda_.FunctionEnvironmentArgs(
            variables={**common_environment, "BROKER_MODE": "bootstrap"},
        ),
        tags=dict(tags),
        opts=pulumi.ResourceOptions.merge(
            child_opts,
            pulumi.ResourceOptions(depends_on=[
                bootstrap_secret, bootstrap_runtime,
            ]),
        ),
    )

    reaper_role, reaper_secret = _create_lambda_role(
        "runnerFleetGithubReaper",
        private_key_secret_arn=args.github_private_key_secret_arn,
        tags=tags,
        child_opts=child_opts,
    )
    reaper_runtime = aws.iam.RolePolicy(
        "runnerFleetGithubReaperRuntime",
        role=reaper_role.id,
        policy=state.lifecycle_state.arn.apply(
            lambda lifecycle_arn: state.queue_activity.arn.apply(
                lambda activity_arn: state.runner_progress.arn.apply(
                    lambda progress_arn: state.runner_completion.arn.apply(
                        lambda completion_arn: _policy([
                {
                    "Effect": "Allow",
                    "Action": ["ssm:GetParameter", "ssm:PutParameter"],
                    "Resource": lifecycle_arn,
                },
                {
                    "Effect": "Allow",
                    "Action": "ssm:GetParameter",
                    "Resource": [
                        activity_arn, progress_arn, completion_arn,
                    ],
                },
                {
                    "Effect": "Allow",
                    "Action": [
                        "ssm:GetParametersByPath", "ssm:DeleteParameter",
                    ],
                    "Resource": bootstrap_arn,
                },
                {
                    "Effect": "Allow",
                    "Action": [
                        "autoscaling:DescribeAutoScalingInstances",
                        "ec2:DescribeInstances",
                    ],
                    "Resource": "*",
                },
                {
                    "Effect": "Allow",
                    "Action": [
                        "autoscaling:SetDesiredCapacity",
                        "autoscaling:TerminateInstanceInAutoScalingGroup",
                    ],
                    "Resource": asg_arn,
                },
                        ])
                    )
                )
            )
        ),
        opts=pulumi.ResourceOptions.merge(
            child_opts,
            # The policy body resolves these ARNs through nested Output.apply
            # calls. Declare the complete graph up front so a saved Pulumi
            # plan and its constrained apply observe identical dependencies.
            pulumi.ResourceOptions(depends_on=[
                state.lifecycle_state,
                state.queue_activity,
                state.runner_progress,
                state.runner_completion,
            ]),
        ),
    )
    reaper_function = aws.lambda_.Function(
        "runnerFleetGithubReaper",
        role=reaper_role.arn,
        runtime=RUNNER_GITHUB_LAMBDA_RUNTIME,
        handler="index.handler",
        timeout=60,
        reserved_concurrent_executions=1,
        code=_lambda_code(),
        environment=aws.lambda_.FunctionEnvironmentArgs(
            variables={**common_environment, "BROKER_MODE": "reaper"},
        ),
        tags=dict(tags),
        opts=pulumi.ResourceOptions.merge(
            child_opts,
            pulumi.ResourceOptions(depends_on=[reaper_secret, reaper_runtime]),
        ),
    )
    schedule = aws.cloudwatch.EventRule(
        "runnerFleetIdleReaperSchedule",
        schedule_expression="rate(1 minute)",
        tags=dict(tags),
        opts=child_opts,
    )
    invoke_permission = aws.lambda_.Permission(
        "runnerFleetIdleReaperInvoke",
        action="lambda:InvokeFunction",
        function=reaper_function.name,
        principal="events.amazonaws.com",
        source_arn=schedule.arn,
        opts=child_opts,
    )
    aws.cloudwatch.EventTarget(
        "runnerFleetIdleReaperTarget",
        rule=schedule.name,
        arn=reaper_function.arn,
        input='{"action":"reap"}',
        opts=pulumi.ResourceOptions.merge(
            child_opts,
            pulumi.ResourceOptions(depends_on=[invoke_permission]),
        ),
    )
    return RunnerGithubBrokerResources(
        bootstrap_function=bootstrap_function,
        queue_activity_parameter=state.queue_activity,
        runner_progress_parameter=state.runner_progress,
        runner_completion_parameter=state.runner_completion,
    )


__all__ = ["RunnerGithubBrokerResources", "create_runner_github_broker"]
