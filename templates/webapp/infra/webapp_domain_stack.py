# AUTO-GENERATED template source: templates/webapp/infra/webapp_domain_stack.py. Do not hand-edit rendered copies; refresh through Yoke template/onboarding surfaces.
"""Pulumi ComponentResource for the webapp domain stack.

Provisions the DNS *control plane* for a project, distinct from the public-edge
stack (`webapp_infra_stack.py`):

- A Route 53 hosted zone for the project's apex domain. This stack CREATES the
  zone (and is the authoritative owner of its lifecycle), then exports its id
  and name servers so the public-edge stack can import the same zone by id.
- Optionally adopts management of the domain *registration*
  (`aws.route53domains.RegisteredDomain`) so the registrant's name servers and
  auto-renew are tracked as code.

Why this is a separate stack from `webapp_infra_stack.py`: that stack is
import-only for the zone (`aws.route53.get_zone(zone_id=...)`) so a prod cutover
never risks the live zone. Zone *creation* is the inverse operation and belongs
to the project that owns the domain. Keeping the two apart preserves the
import-only safety boundary on the public-edge stack.

Registration is a two-step operator reality, not a one-shot automation:

1. Route 53 domain registration (the actual purchase) requires an AWS-console
   final-step click-through — TLD availability, registrant contact, and payment
   cannot be fully driven by IaC. The operator buys the domain in the console.
2. Once the domain is registered AND this stack has created the zone, the
   operator flips `manage_registration=true` and re-runs so Pulumi points the
   registration's name servers at the created zone and manages auto-renew.

The default (`manage_registration=false`) is the honest partial state: the zone
exists and is ready, the registration is pending the operator's console step.
This stack is never "broken" in that state — it simply has not yet adopted the
registration resource.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

import pulumi
import pulumi_aws as aws
from webapp_dns_records import (
    DomainMxRecordArgs,
    DomainTxtRecordArgs,
    create_domain_mx_records,
    create_domain_txt_records,
)


@dataclass
class WebappDomainArgs:
    """Inputs for ``WebappDomainStack``."""

    domain_name: str
    project_name: str
    # Existing hosted-zone id to ADOPT instead of creating a new zone. Set this
    # when the zone already exists — most importantly when the domain was
    # registered THROUGH Route 53, which auto-creates a public hosted zone the
    # domain delegates to. Adopting (Pulumi ``import``) avoids creating a
    # duplicate, orphaned zone with different name servers. Empty (default) =
    # create a fresh zone, for domains registered elsewhere.
    import_zone_id: str = ""
    # When False (default), only the hosted zone is managed — the honest
    # pre-registration partial state. When True, the stack also adopts the
    # already-registered domain via ``aws.route53domains.RegisteredDomain`` and
    # points its name servers at the zone. Flip to True only after the operator
    # has completed the console registration purchase.
    manage_registration: bool = False
    # Registration auto-renew, only consulted when ``manage_registration`` is
    # True. Defaults to True so a managed registration does not silently lapse.
    registration_auto_renew: bool = True
    domain_txt_records: Sequence[DomainTxtRecordArgs] = ()
    domain_mx_records: Sequence[DomainMxRecordArgs] = ()


class WebappDomainStack(pulumi.ComponentResource):
    """Route 53 hosted zone (always) + optional registration management."""

    hosted_zone: aws.route53.Zone
    registered_domain: Optional[aws.route53domains.RegisteredDomain]

    def __init__(
        self,
        name: str,
        args: WebappDomainArgs,
        opts: Optional[pulumi.ResourceOptions] = None,
    ) -> None:
        super().__init__("webapp:infra:WebappDomainStack", name, None, opts)

        tags = {"project": args.project_name}
        child_opts = pulumi.ResourceOptions(parent=self)

        # --- Route 53 hosted zone (create, or adopt an existing one) ---
        # When ``import_zone_id`` is set, adopt the existing zone via Pulumi's
        # import option rather than creating a new one. The adopting ``pulumi
        # up`` reconciles declared inputs (comment/tags) onto the imported zone;
        # preview it first. When unset, a fresh zone is created.
        zone_opts = child_opts
        if args.import_zone_id:
            zone_opts = pulumi.ResourceOptions.merge(
                child_opts,
                pulumi.ResourceOptions(import_=args.import_zone_id),
            )
        self.hosted_zone = aws.route53.Zone(
            "hostedZone",
            name=args.domain_name,
            comment=f"{args.project_name}: apex hosted zone (managed by webapp domain stack)",
            tags=tags,
            opts=zone_opts,
        )

        # --- Optional: adopt management of the domain registration ---
        # ``aws.route53domains.RegisteredDomain`` MANAGES a domain already
        # registered in this AWS account; it does not perform the purchase.
        # Gated behind ``manage_registration`` so the zone can be stood up
        # before the operator completes the console registration step.
        self.registered_domain = None
        if args.manage_registration:
            self.registered_domain = aws.route53domains.RegisteredDomain(
                "registeredDomain",
                domain_name=args.domain_name,
                auto_renew=args.registration_auto_renew,
                name_servers=self.hosted_zone.name_servers.apply(
                    lambda servers: [
                        aws.route53domains.RegisteredDomainNameServerArgs(name=ns)
                        for ns in servers
                    ]
                ),
                tags=tags,
                opts=child_opts,
            )

        create_domain_txt_records(
            domain_name=args.domain_name,
            hosted_zone_id=self.hosted_zone.zone_id,
            records=args.domain_txt_records,
            opts=child_opts,
        )
        create_domain_mx_records(
            domain_name=args.domain_name,
            hosted_zone_id=self.hosted_zone.zone_id,
            records=args.domain_mx_records,
            opts=child_opts,
        )

        # --- Exports for downstream stacks and the project handoff ---
        # ``hostedZoneId`` is the value later DNS work (public-edge stack,
        # ACM, CloudFront alias records) consumes via the import-only path.
        pulumi.export("hostedZoneId", self.hosted_zone.zone_id)
        pulumi.export("hostedZoneName", self.hosted_zone.name)
        pulumi.export("hostedZoneNameServers", self.hosted_zone.name_servers)
        pulumi.export("registrationManaged", args.manage_registration)

        self.register_outputs(
            {
                "hostedZoneId": self.hosted_zone.zone_id,
                "hostedZoneName": self.hosted_zone.name,
                "hostedZoneNameServers": self.hosted_zone.name_servers,
                "registrationManaged": args.manage_registration,
            }
        )
