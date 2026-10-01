"""How the runner fleet's Auto Scaling group buys capacity.

Runners are disposable: a reclaimed instance fails one job, which reruns.
That makes spare (spot) capacity the right default and buys the fleet at a
fraction of on-demand. An Auto Scaling group can only hold spot through a
mixed-instances policy, so the policy carries the launch template instead of
the group's plain ``launch_template`` argument — even when the fleet is
configured entirely on-demand.
"""

from __future__ import annotations

import pulumi_aws as aws


def spot_capacity_policy(launch_template_id, args):
    """Build the group's mixed-instances policy from the fleet's spot posture."""
    return aws.autoscaling.GroupMixedInstancesPolicyArgs(
        launch_template=aws.autoscaling.GroupMixedInstancesPolicyLaunchTemplateArgs(
            launch_template_specification=(
                aws.autoscaling.GroupMixedInstancesPolicyLaunchTemplateLaunchTemplateSpecificationArgs(
                    launch_template_id=launch_template_id,
                    version="$Latest",
                )
            ),
        ),
        instances_distribution=(
            aws.autoscaling.GroupMixedInstancesPolicyInstancesDistributionArgs(
                on_demand_base_capacity=args.spot_on_demand_base_capacity,
                on_demand_percentage_above_base_capacity=(
                    args.spot_on_demand_percentage_above_base
                ),
                # Weigh spare capacity depth alongside price so the fleet lands
                # in pools it is less likely to be reclaimed from mid-job.
                spot_allocation_strategy="price-capacity-optimized",
            )
        ),
    )


__all__ = ["spot_capacity_policy"]
