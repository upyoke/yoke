"""Scheduled stop/start for a VPS instance that is only needed some hours.

A non-production host billed around the clock is paid for mostly while
nobody is using it. Two EventBridge schedules stop it and start it again on
a cron the operator declares, using the scheduler's direct EC2 calls rather
than a Lambda, so there is no function to deploy or keep alive.

Inert unless both crons are declared: an existing stack that says nothing
about power schedules creates no role and no schedules, and its instance
keeps running exactly as before.

Two things to weigh before turning this on for a host:

* anything that SSHes to the host on a schedule of its own — CI deploys,
  for instance — fails while it is stopped, so the running window has to
  cover those;
* the instance keeps its root volume and its Elastic IP while stopped, and
  both keep billing. The saving is the instance-hours, not the whole host.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pulumi
import pulumi_aws as aws

#: EventBridge Scheduler calls EC2 directly through a universal target ARN.
_STOP_TARGET = "arn:aws:scheduler:::aws-sdk:ec2:stopInstances"
_START_TARGET = "arn:aws:scheduler:::aws-sdk:ec2:startInstances"


@dataclass
class VpsPowerScheduleArgs:
    """When a VPS instance should be running.

    ``stop_cron`` and ``start_cron`` are EventBridge cron expressions without
    the ``cron(...)`` wrapper, e.g. ``0 20 ? * MON-FRI *``. Both empty turns
    the feature off.
    """

    stop_cron: str = ""
    start_cron: str = ""
    timezone: str = "UTC"

    @property
    def enabled(self) -> bool:
        return bool(self.stop_cron.strip() and self.start_cron.strip())


def attach_power_schedule(
    component: pulumi.ComponentResource,
    *,
    instance_id: pulumi.Input[str],
    args: VpsPowerScheduleArgs,
    tags: dict,
    child_opts: pulumi.ResourceOptions,
) -> Optional[aws.iam.Role]:
    """Create the stop/start schedules. Returns ``None`` when not configured."""
    if not args.enabled:
        return None

    role = aws.iam.Role(
        "vpsPowerScheduleRole",
        assume_role_policy=pulumi.Output.json_dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"Service": "scheduler.amazonaws.com"},
                        "Action": "sts:AssumeRole",
                    }
                ],
            }
        ),
        tags=tags,
        opts=child_opts,
    )
    # Scoped to this one instance: a schedule that can stop the whole account's
    # fleet is a much larger blast radius than the saving justifies.
    aws.iam.RolePolicy(
        "vpsPowerSchedulePolicy",
        role=role.id,
        policy=pulumi.Output.json_dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": ["ec2:StopInstances", "ec2:StartInstances"],
                        "Resource": pulumi.Output.concat(
                            "arn:aws:ec2:*:*:instance/", instance_id
                        ),
                    }
                ],
            }
        ),
        opts=child_opts,
    )

    for name, cron, target in (
        ("vpsPowerScheduleStop", args.stop_cron, _STOP_TARGET),
        ("vpsPowerScheduleStart", args.start_cron, _START_TARGET),
    ):
        aws.scheduler.Schedule(
            name,
            schedule_expression=f"cron({cron.strip()})",
            schedule_expression_timezone=args.timezone,
            flexible_time_window=aws.scheduler.ScheduleFlexibleTimeWindowArgs(
                mode="OFF",
            ),
            target=aws.scheduler.ScheduleTargetArgs(
                arn=target,
                role_arn=role.arn,
                input=pulumi.Output.json_dumps(
                    {"InstanceIds": [instance_id]}
                ),
            ),
            opts=child_opts,
        )
    return role


__all__ = ["VpsPowerScheduleArgs", "attach_power_schedule"]
