# AUTO-GENERATED template source: templates/webapp/infra/webapp_runner_fleet_network.py. Do not hand-edit rendered copies; refresh through Yoke template/onboarding surfaces.
"""Dedicated network boundary for root-capable GitHub Actions runners."""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
from typing import Mapping, Sequence

import pulumi
import pulumi_aws as aws


@dataclass(frozen=True)
class RunnerFleetNetwork:
    """Isolated VPC resources consumed by the runner launch template."""

    vpc: aws.ec2.Vpc
    subnet: aws.ec2.Subnet
    security_group: aws.ec2.SecurityGroup


def create_runner_network(
    *,
    tags: Mapping[str, str],
    deployment_ssh_stack_names: Sequence[str],
    child_opts: pulumi.ResourceOptions,
) -> RunnerFleetNetwork:
    """Provision an isolated public VPC with explicit workflow egress."""
    vpc = aws.ec2.Vpc(
        "runnerFleetVpc",
        cidr_block="10.253.0.0/24",
        enable_dns_support=True,
        enable_dns_hostnames=True,
        tags=dict(tags),
        opts=child_opts,
    )
    internet_gateway = aws.ec2.InternetGateway(
        "runnerFleetInternetGateway",
        vpc_id=vpc.id,
        tags=dict(tags),
        opts=child_opts,
    )
    subnet = aws.ec2.Subnet(
        "runnerFleetSubnet",
        vpc_id=vpc.id,
        cidr_block="10.253.0.0/25",
        map_public_ip_on_launch=True,
        tags=dict(tags),
        opts=child_opts,
    )
    route_table = aws.ec2.RouteTable(
        "runnerFleetRouteTable",
        vpc_id=vpc.id,
        tags=dict(tags),
        opts=child_opts,
    )
    route = aws.ec2.Route(
        "runnerFleetInternetRoute",
        route_table_id=route_table.id,
        destination_cidr_block="0.0.0.0/0",
        gateway_id=internet_gateway.id,
        opts=child_opts,
    )
    aws.ec2.RouteTableAssociation(
        "runnerFleetRouteTableAssociation",
        subnet_id=subnet.id,
        route_table_id=route_table.id,
        opts=pulumi.ResourceOptions.merge(
            child_opts,
            pulumi.ResourceOptions(depends_on=[route]),
        ),
    )
    egress = [
        _egress("HTTPS package and GitHub access", "tcp", 443, "0.0.0.0/0"),
        _egress("HTTP package repositories", "tcp", 80, "0.0.0.0/0"),
        _egress("VPC DNS over UDP", "udp", 53, "10.253.0.2/32"),
        _egress("VPC DNS over TCP", "tcp", 53, "10.253.0.2/32"),
    ]
    for stack_name in deployment_ssh_stack_names:
        egress.append(
            _egress(
                f"SSH to deployment environment stack {stack_name}",
                "tcp",
                22,
                _deployment_ssh_cidr(stack_name),
            )
        )
    security_group = aws.ec2.SecurityGroup(
        "runnerFleetSecurityGroup",
        vpc_id=vpc.id,
        description="Isolated GitHub Actions runner egress",
        ingress=[],
        egress=egress,
        tags=dict(tags),
        opts=child_opts,
    )
    return RunnerFleetNetwork(
        vpc=vpc, subnet=subnet, security_group=security_group,
    )


def _deployment_ssh_cidr(stack_name: str) -> pulumi.Output[str]:
    reference = pulumi.StackReference(stack_name)
    return reference.require_output("originElasticIpAddress").apply(
        _exact_ipv4_cidr
    )


def _exact_ipv4_cidr(raw_address: object) -> str:
    try:
        address = ipaddress.ip_address(str(raw_address))
    except ValueError as exc:
        raise pulumi.RunError(
            "runner-fleet deployment bastion Elastic IP is invalid"
        ) from exc
    if address.version != 4:
        raise pulumi.RunError(
            "runner-fleet deployment bastion must use an IPv4 Elastic IP"
        )
    return f"{address}/32"


def _egress(
    description: str, protocol: str, port: int, cidr: pulumi.Input[str],
) -> aws.ec2.SecurityGroupEgressArgs:
    return aws.ec2.SecurityGroupEgressArgs(
        description=description,
        protocol=protocol,
        from_port=port,
        to_port=port,
        cidr_blocks=[cidr],
    )


__all__ = ["RunnerFleetNetwork", "create_runner_network"]
