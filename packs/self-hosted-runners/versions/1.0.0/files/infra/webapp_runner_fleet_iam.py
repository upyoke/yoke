"""Least-privilege IAM resources for the GitHub Actions runner fleet."""

from __future__ import annotations

import json
from typing import Mapping

import pulumi
import pulumi_aws as aws

from webapp_runner_fleet_internals import _assume_role_policy


def _runtime_policy(statements: list[dict]) -> str:
    return json.dumps({"Version": "2012-10-17", "Statement": statements})


def create_instance_identity(
    *, tags: Mapping[str, str], child_opts: pulumi.ResourceOptions,
) -> tuple[aws.iam.Role, aws.iam.InstanceProfile]:
    """Create the EC2 role without granting access to GitHub credentials."""
    role = aws.iam.Role(
        "runnerFleetInstanceRole",
        assume_role_policy=_assume_role_policy("ec2.amazonaws.com"),
        tags=dict(tags),
        opts=child_opts,
    )
    profile = aws.iam.InstanceProfile(
        "runnerFleetInstanceProfile",
        role=role.name,
        tags=dict(tags),
        opts=child_opts,
    )
    return role, profile


def grant_instance_runtime(
    role: aws.iam.Role,
    *,
    broker_arn: pulumi.Input[str],
    child_opts: pulumi.ResourceOptions,
) -> aws.iam.RolePolicy:
    """Allow invocation of the broker's one-time bootstrap action."""
    policy = broker_arn.apply(
        lambda broker: _runtime_policy([{
            "Effect": "Allow",
            "Action": "lambda:InvokeFunction",
            "Resource": broker,
        }])
    )
    return aws.iam.RolePolicy(
        "runnerFleetInstanceRuntime",
        role=role.id,
        policy=policy,
        opts=child_opts,
    )


def create_webhook_identity(
    *, tags: Mapping[str, str], child_opts: pulumi.ResourceOptions,
) -> aws.iam.Role:
    """Create the scaling webhook Lambda execution role."""
    role = aws.iam.Role(
        "runnerFleetWebhookRole",
        assume_role_policy=_assume_role_policy("lambda.amazonaws.com"),
        tags=dict(tags),
        opts=child_opts,
    )
    aws.iam.RolePolicyAttachment(
        "runnerFleetWebhookLogs",
        role=role.name,
        policy_arn="arn:aws:iam::aws:policy/service-role/"
        "AWSLambdaBasicExecutionRole",
        opts=child_opts,
    )
    return role


def grant_webhook_runtime(
    role: aws.iam.Role,
    *,
    parameter_arn: pulumi.Input[str],
    queue_activity_arn: pulumi.Input[str],
    runner_progress_arn: pulumi.Input[str],
    runner_completion_arn: pulumi.Input[str],
    asg_arn: pulumi.Input[str],
    child_opts: pulumi.ResourceOptions,
) -> aws.iam.RolePolicy:
    """Allow only the webhook secret read and its runner ASG scale-up."""
    policy = parameter_arn.apply(
        lambda parameter: queue_activity_arn.apply(
            lambda activity: runner_progress_arn.apply(
                lambda progress: runner_completion_arn.apply(
                    lambda completion: asg_arn.apply(
                        lambda asg: _runtime_policy([
                {
                    "Effect": "Allow",
                    "Action": "ssm:GetParameter",
                    "Resource": parameter,
                },
                {
                    "Effect": "Allow",
                    "Action": "ssm:PutParameter",
                    "Resource": [activity, progress, completion],
                },
                {
                    "Effect": "Allow",
                    "Action": "autoscaling:SetDesiredCapacity",
                    "Resource": asg,
                },
                        ])
                    )
                )
            )
        )
    )
    return aws.iam.RolePolicy(
        "runnerFleetWebhookRuntime",
        role=role.id,
        policy=policy,
        opts=child_opts,
    )


__all__ = [
    "create_instance_identity",
    "create_webhook_identity",
    "grant_instance_runtime",
    "grant_webhook_runtime",
]
