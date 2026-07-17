# AUTO-GENERATED template source: templates/webapp/infra/webapp_dns_records.py. Do not hand-edit rendered copies; refresh through Yoke template/onboarding surfaces.
"""Shared Route 53 record helpers for webapp Pulumi stacks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import pulumi
import pulumi_aws as aws


@dataclass(frozen=True)
class DomainTxtRecordArgs:
    """One TXT record inside the project's hosted zone."""

    name: str
    values: Sequence[str]
    ttl: int = 300
    resource_name: str = ""


@dataclass(frozen=True)
class DomainMxRecordArgs:
    """One MX record set inside the project's hosted zone."""

    name: str
    values: Sequence[str]
    ttl: int = 300
    resource_name: str = ""


def create_domain_txt_records(
    *,
    domain_name: str,
    hosted_zone_id: pulumi.Input[str],
    records: Sequence[DomainTxtRecordArgs],
    opts: pulumi.ResourceOptions,
) -> None:
    """Create domain-level TXT records declared in project settings."""
    for index, record in enumerate(records):
        aws.route53.Record(
            f"domainTxtRecord{_resource_suffix(record, index)}",
            zone_id=hosted_zone_id,
            name=_record_name(domain_name, record.name),
            type="TXT",
            ttl=record.ttl,
            records=list(record.values),
            opts=opts,
        )


def create_domain_mx_records(
    *,
    domain_name: str,
    hosted_zone_id: pulumi.Input[str],
    records: Sequence[DomainMxRecordArgs],
    opts: pulumi.ResourceOptions,
) -> None:
    """Create domain-level MX records declared in project settings."""
    for index, record in enumerate(records):
        aws.route53.Record(
            f"domainMxRecord{_resource_suffix(record, index)}",
            zone_id=hosted_zone_id,
            name=_record_name(domain_name, record.name),
            type="MX",
            ttl=record.ttl,
            records=list(record.values),
            opts=opts,
        )


def _record_name(domain_name: str, record_name: str) -> str:
    domain = domain_name.strip().rstrip(".")
    name = record_name.strip().rstrip(".")
    if not name or name == "@":
        return domain
    if name == domain or name.endswith(f".{domain}"):
        return name
    return f"{name}.{domain}"


def _resource_suffix(record: DomainTxtRecordArgs, index: int) -> str:
    source = record.resource_name or record.name or f"record{index}"
    normalized = "".join(ch for ch in source.title() if ch.isalnum())
    if not normalized:
        normalized = f"Record{index}"
    return f"{normalized}{index}"
