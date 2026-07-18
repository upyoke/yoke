# AUTO-GENERATED template source: templates/webapp/infra/webapp_vps_stack.py. Do not hand-edit rendered copies; refresh through Yoke template/onboarding surfaces.
"""Pulumi ComponentResource for the webapp VPS stack.

Provisions:
- EC2 instance (default ``t4g.medium`` ARM Graviton) running Ubuntu 24.04
- gp3 encrypted root volume sized by ``root_volume_gb``
- Elastic IP attached to the instance
- Security group allowing inbound 22 (SSH), 80 (HTTP), 443 (HTTPS); all outbound

Access is via the configured key pair plus any IAM instance profile passed
through ``iam_instance_profile_name``. The ``vps_iam_instance_profile_name``
config key attaches a profile granting ECR image pull, CloudWatch log shipping,
artifact-bucket access, and AWS Session Manager recovery access; ``None`` (the
default) keeps standalone legacy VPS stacks SSH-only.

Ops bootstrap (Docker, nginx, certbot, etc.) runs separately via the rendered
``ops/provision-ec2.sh`` after first boot.

The origin host A record is intentionally NOT managed here — it is
flipped out-of-band via ``aws route53 change-resource-record-sets`` so the
``pulumi up`` completes before the cutover step that actually flips production
traffic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Sequence

import pulumi
import pulumi_aws as aws

# Graviton (ARM64) instance families supported by the template.
_GRAVITON_PREFIX = re.compile(r"^(t4g|c7g|m7g|r7g|c6g|m6g|r6g|a1)\.")


def _ami_arch_for_instance(instance_type: str) -> str:
    """Map an instance type to its Ubuntu AMI architecture."""
    return "arm64" if _GRAVITON_PREFIX.match(instance_type) else "amd64"


@dataclass
class WebappVpsArgs:
    """Inputs for ``WebappVpsStack``."""

    deploy_namespace: str
    instance_type: str
    root_volume_gb: int
    ssh_key_name: str
    # Pulumi stack name (e.g. ``"buzz-vps"``). Used as the prefix for
    # ``Name`` tags so ``pulumi import`` lands a zero-change diff against
    # existing live VPS instances tagged with the historical phrasing.
    # Always populated from ``pulumi.get_stack()`` in
    # ``_vps_args_from_config`` — no template-level default.
    stack_name: str
    # IAM instance profile attached to the instance. ``None`` (default) keeps
    # the instance profile absent — legacy ``-vps`` stacks change nothing.
    # ``vps_iam_instance_profile_name`` supplies a profile when required.
    iam_instance_profile_name: Optional[pulumi.Input[str]] = None
    component_type_aliases: Sequence[str] = ()


class WebappVpsStack(pulumi.ComponentResource):
    """Single-VPS EC2 instance with an Elastic IP and public-web security group."""

    instance: aws.ec2.Instance
    elastic_ip: aws.ec2.Eip
    security_group: aws.ec2.SecurityGroup

    def __init__(
        self,
        name: str,
        args: WebappVpsArgs,
        opts: Optional[pulumi.ResourceOptions] = None,
    ) -> None:
        component_opts = pulumi.ResourceOptions.merge(
            opts,
            pulumi.ResourceOptions(
                aliases=[
                    pulumi.Alias(type_=value)
                    for value in args.component_type_aliases
                ]
            ),
        )
        super().__init__(
            "webapp:infra:WebappVpsStack",
            name,
            None,
            component_opts,
        )

        tags = {"project": args.deploy_namespace}
        child_opts = pulumi.ResourceOptions(parent=self)

        # --- Networking: default VPC + public subnet ---
        # Founder-mode posture: no custom VPC, no private subnets, no NAT.
        default_vpc = aws.ec2.get_vpc(default=True)

        # --- Security group ---
        self.security_group = aws.ec2.SecurityGroup(
            "vpsSecurityGroup",
            vpc_id=default_vpc.id,
            description=f"{args.deploy_namespace} VPS - public web + SSH",
            ingress=[
                aws.ec2.SecurityGroupIngressArgs(
                    description="SSH from anywhere",
                    protocol="tcp",
                    from_port=22,
                    to_port=22,
                    cidr_blocks=["0.0.0.0/0"],
                ),
                aws.ec2.SecurityGroupIngressArgs(
                    description="HTTP from anywhere (redirects to HTTPS)",
                    protocol="tcp",
                    from_port=80,
                    to_port=80,
                    cidr_blocks=["0.0.0.0/0"],
                ),
                aws.ec2.SecurityGroupIngressArgs(
                    description="HTTPS from anywhere",
                    protocol="tcp",
                    from_port=443,
                    to_port=443,
                    cidr_blocks=["0.0.0.0/0"],
                ),
            ],
            egress=[
                aws.ec2.SecurityGroupEgressArgs(
                    # Matches the description phrasing on the existing live
                    # security group so ``pulumi import`` is zero-change.
                    description="Allow all outbound traffic by default",
                    protocol="-1",
                    from_port=0,
                    to_port=0,
                    cidr_blocks=["0.0.0.0/0"],
                ),
            ],
            tags=tags,
            opts=child_opts,
        )

        # --- AMI: latest Ubuntu 24.04 LTS published by Canonical ---
        # Architecture follows the instance type's prefix; resolved at deploy
        # time from SSM Parameter Store so new deploys pick up patched AMIs
        # automatically.
        arch = _ami_arch_for_instance(args.instance_type)
        ami_param = aws.ssm.get_parameter(
            name=f"/aws/service/canonical/ubuntu/server/24.04/stable/current/{arch}/hvm/ebs-gp3/ami-id",
        )

        # --- EC2 instance ---
        # ``user_data`` is set to a bare ``#!/bin/bash`` shebang to match
        # the existing live instance, which carries the same 17-byte stub.
        # Ops bootstrap (Docker, nginx, certbot, etc.) is intentionally NOT
        # inlined here — it runs separately via
            # the rendered ``ops/provision-ec2.sh`` after first boot,
        # keeping ``pulumi up`` decoupled from runtime provisioning.
        #
        # ``Name`` tag is set to the historical ``"{stack-name}/VpsInstance"``
        # phrasing on top of the project tag so zero-change cutover from
        # the live instance holds. The stack name comes from the
        # ``WebappVpsArgs.stack_name`` arg.
        instance_tags = {
            **tags,
            "Name": f"{args.stack_name}/VpsInstance",
        }
        # ``ignore_changes=["ami"]``: the AMI is resolved from the SSM
        # parameter at creation time; live single-box envs are stateful pets
        # and must not be proposed for replacement by AMI drift on routine
        # ``pulumi up``. Refreshing the AMI is an explicit operator action
        # (targeted replace).
        instance_opts = pulumi.ResourceOptions.merge(
            child_opts,
            pulumi.ResourceOptions(ignore_changes=["ami"]),
        )
        self.instance = aws.ec2.Instance(
            "vpsInstance",
            ami=ami_param.value,
            instance_type=args.instance_type,
            key_name=args.ssh_key_name,
            iam_instance_profile=args.iam_instance_profile_name,
            vpc_security_group_ids=[self.security_group.id],
            user_data="#!/bin/bash",
            # ``user_data_replace_on_change`` is set explicitly to ``False``
            # to drop the provider's structural diff against the imported
            # state, which carries the field as unset/null. Behavior is
            # in-place update on userData change, not instance replacement
            # — same as the existing live instance.
            user_data_replace_on_change=False,
            root_block_device=aws.ec2.InstanceRootBlockDeviceArgs(
                volume_size=args.root_volume_gb,
                volume_type="gp3",
                delete_on_termination=True,
                encrypted=True,
            ),
            associate_public_ip_address=True,
            tags=instance_tags,
            opts=instance_opts,
        )

        # --- Elastic IP ---
        self.elastic_ip = aws.ec2.Eip(
            "vpsElasticIp",
            domain="vpc",
            instance=self.instance.id,
            tags=tags,
            opts=child_opts,
        )

        # --- Exports for downstream ops scripts ---
        pulumi.export("vpsInstanceId", self.instance.id)
        pulumi.export("vpsElasticIpAddress", self.elastic_ip.public_ip)
        pulumi.export("vpsPublicDnsName", self.instance.public_dns)
        pulumi.export("vpsSecurityGroupId", self.security_group.id)

        self.register_outputs(
            {
                "vpsInstanceId": self.instance.id,
                "vpsElasticIpAddress": self.elastic_ip.public_ip,
                "vpsPublicDnsName": self.instance.public_dns,
                "vpsSecurityGroupId": self.security_group.id,
            }
        )
