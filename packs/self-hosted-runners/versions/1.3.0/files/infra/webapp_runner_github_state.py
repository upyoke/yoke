"""Durable coordination state for the GitHub Actions runner fleet."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import pulumi
import pulumi_aws as aws


@dataclass(frozen=True)
class RunnerGithubStateResources:
    """Parameters shared by the webhook and lifecycle broker."""

    lifecycle_state: aws.ssm.Parameter
    queue_activity: aws.ssm.Parameter
    runner_progress: aws.ssm.Parameter
    runner_completion: aws.ssm.Parameter


def _parameter(
    resource_name: str,
    *,
    name: str,
    value: str,
    tags: Mapping[str, str],
    child_opts: pulumi.ResourceOptions,
) -> aws.ssm.Parameter:
    return aws.ssm.Parameter(
        resource_name,
        name=name,
        type="String",
        value=value,
        tags=dict(tags),
        opts=pulumi.ResourceOptions.merge(
            child_opts,
            pulumi.ResourceOptions(ignore_changes=["value"]),
        ),
    )


def create_runner_github_state(
    parameter_prefix: str,
    *,
    tags: Mapping[str, str],
    child_opts: pulumi.ResourceOptions,
) -> RunnerGithubStateResources:
    """Create independent monotonic job-progress and completion channels."""
    event_initial = '{"action":"none","runner_name":"","job_id":"","at":0}'
    return RunnerGithubStateResources(
        lifecycle_state=_parameter(
            "runnerFleetLifecycleState",
            name=f"{parameter_prefix}/lifecycle-state",
            value=(
                '{"idle_since":0,"queue_activity":"initial",'
                '"bootstrap_failures":0,"online_instance_id":""}'
            ),
            tags=tags,
            child_opts=child_opts,
        ),
        queue_activity=_parameter(
            "runnerFleetQueueActivity",
            name=f"{parameter_prefix}/queue-activity",
            value="initial",
            tags=tags,
            child_opts=child_opts,
        ),
        runner_progress=_parameter(
            "runnerFleetRunnerProgress",
            name=f"{parameter_prefix}/runner-progress",
            value=event_initial,
            tags=tags,
            child_opts=child_opts,
        ),
        runner_completion=_parameter(
            "runnerFleetRunnerCompletion",
            name=f"{parameter_prefix}/runner-completion",
            value=event_initial,
            tags=tags,
            child_opts=child_opts,
        ),
    )


__all__ = ["RunnerGithubStateResources", "create_runner_github_state"]
