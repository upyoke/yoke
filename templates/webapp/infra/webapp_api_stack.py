# AUTO-GENERATED template source: templates/webapp/infra/webapp_api_stack.py. Do not hand-edit rendered copies; refresh through Yoke template/onboarding surfaces.
"""Pulumi ComponentResource for a webapp API public edge."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import pulumi
import pulumi_aws as aws

_CLOUDFRONT_ZONE_ID = "Z2FDTNDATAQYW2"
_CACHE_DISABLED_POLICY_ID = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"
_ALL_VIEWER_ORIGIN_REQUEST_POLICY_ID = "216adef6-5c7f-47e4-b989-5492eafa07d3"


@dataclass
class WebappApiArgs:
    project_name: str
    environment: str
    domain_name: str
    api_host: str
    origin_host: str
    hosted_zone_id: str
    origin_ip: pulumi.Input[str]
    api_origin_port: int
    distribution_bucket_name: str = ""
    distribution_origin_id: str = ""


def _validation_field(options: Any, index: int, field: str) -> Any:
    option = options[index]
    if isinstance(option, dict):
        return option[field]
    return getattr(option, field)


class WebappApiStack(pulumi.ComponentResource):
    """CloudFront, TLS, and DNS for the project API hostname."""

    certificate: aws.acm.Certificate
    distribution: aws.cloudfront.Distribution
    api_record: aws.route53.Record
    api_ipv6_record: aws.route53.Record
    origin_record: aws.route53.Record
    distribution_bucket: Optional[aws.s3.BucketV2]
    distribution_bucket_policy: Optional[aws.s3.BucketPolicy]

    def __init__(
        self,
        name: str,
        args: WebappApiArgs,
        opts: Optional[pulumi.ResourceOptions] = None,
    ) -> None:
        super().__init__("webapp:infra:WebappApiStack", name, None, opts)

        tags = {
            "project": args.project_name,
            "environment": args.environment,
        }
        child_opts = pulumi.ResourceOptions(parent=self)
        origin_id = f"{args.project_name}-{args.environment}-api-origin"

        aws.route53.get_zone(zone_id=args.hosted_zone_id)
        self.certificate = aws.acm.Certificate(
            "apiCertificate",
            domain_name=args.api_host,
            subject_alternative_names=[args.origin_host],
            validation_method="DNS",
            tags=tags,
            opts=child_opts,
        )

        validation_records = []
        for index, label in enumerate(("api", "origin")):
            validation_records.append(
                aws.route53.Record(
                    f"{label}CertificateValidation",
                    zone_id=args.hosted_zone_id,
                    name=self.certificate.domain_validation_options.apply(
                        lambda options, i=index: _validation_field(
                            options, i, "resource_record_name",
                        )
                    ),
                    type=self.certificate.domain_validation_options.apply(
                        lambda options, i=index: _validation_field(
                            options, i, "resource_record_type",
                        )
                    ),
                    records=[
                        self.certificate.domain_validation_options.apply(
                            lambda options, i=index: _validation_field(
                                options, i, "resource_record_value",
                            )
                        )
                    ],
                    ttl=300,
                    allow_overwrite=True,
                    opts=child_opts,
                )
            )

        validation = aws.acm.CertificateValidation(
            "apiCertificateValidation",
            certificate_arn=self.certificate.arn,
            validation_record_fqdns=[record.fqdn for record in validation_records],
            opts=child_opts,
        )
        distribution_opts = pulumi.ResourceOptions.merge(
            child_opts,
            pulumi.ResourceOptions(depends_on=[validation]),
        )

        app_origin = aws.cloudfront.DistributionOriginArgs(
            origin_id=origin_id,
            domain_name=args.origin_host,
            custom_origin_config=aws.cloudfront.DistributionOriginCustomOriginConfigArgs(
                http_port=args.api_origin_port,
                https_port=443,
                origin_protocol_policy="http-only",
                origin_ssl_protocols=["TLSv1.2"],
            ),
            custom_headers=[
                aws.cloudfront.DistributionOriginCustomHeaderArgs(
                    name="X-Forwarded-Host",
                    value=args.api_host,
                ),
            ],
        )

        from webapp_distribution_stack import build_distribution_hosting

        distribution_hosting = build_distribution_hosting(
            project_name=args.project_name,
            distribution_bucket_name=args.distribution_bucket_name,
            distribution_origin_id=(
                args.distribution_origin_id
                or f"{args.project_name}-{args.environment}-distribution-static"
            ),
            app_origin=app_origin,
            tags=tags,
            child_opts=child_opts,
        )
        self.distribution_bucket = distribution_hosting.bucket
        self.distribution_bucket_policy = None

        self.distribution = aws.cloudfront.Distribution(
            "apiDistribution",
            enabled=True,
            is_ipv6_enabled=True,
            comment=f"{args.project_name} {args.environment} API edge",
            aliases=[args.api_host],
            origins=distribution_hosting.origins,
            default_cache_behavior=aws.cloudfront.DistributionDefaultCacheBehaviorArgs(
                target_origin_id=origin_id,
                viewer_protocol_policy="redirect-to-https",
                compress=True,
                cache_policy_id=_CACHE_DISABLED_POLICY_ID,
                origin_request_policy_id=_ALL_VIEWER_ORIGIN_REQUEST_POLICY_ID,
                allowed_methods=[
                    "GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE",
                ],
                cached_methods=["GET", "HEAD"],
            ),
            ordered_cache_behaviors=distribution_hosting.ordered_cache_behaviors,
            viewer_certificate=aws.cloudfront.DistributionViewerCertificateArgs(
                acm_certificate_arn=validation.certificate_arn,
                ssl_support_method="sni-only",
                minimum_protocol_version="TLSv1.2_2021",
            ),
            restrictions=aws.cloudfront.DistributionRestrictionsArgs(
                geo_restriction=aws.cloudfront.DistributionRestrictionsGeoRestrictionArgs(
                    restriction_type="none",
                ),
            ),
            tags=tags,
            opts=distribution_opts,
        )
        if self.distribution_bucket is not None:
            from webapp_distribution_stack import attach_distribution_bucket_policy

            self.distribution_bucket_policy = attach_distribution_bucket_policy(
                bucket=self.distribution_bucket,
                bucket_name=args.distribution_bucket_name,
                origin_access_identity_arn=(
                    distribution_hosting.origin_access_identity_arn
                ),
                child_opts=child_opts,
            )

        self.api_record = aws.route53.Record(
            "apiA",
            zone_id=args.hosted_zone_id,
            name=args.api_host,
            type="A",
            aliases=[
                aws.route53.RecordAliasArgs(
                    name=self.distribution.domain_name,
                    zone_id=_CLOUDFRONT_ZONE_ID,
                    evaluate_target_health=False,
                ),
            ],
            opts=child_opts,
        )
        self.api_ipv6_record = aws.route53.Record(
            "apiAAAA",
            zone_id=args.hosted_zone_id,
            name=args.api_host,
            type="AAAA",
            aliases=[
                aws.route53.RecordAliasArgs(
                    name=self.distribution.domain_name,
                    zone_id=_CLOUDFRONT_ZONE_ID,
                    evaluate_target_health=False,
                ),
            ],
            opts=child_opts,
        )
        self.origin_record = aws.route53.Record(
            "originA",
            zone_id=args.hosted_zone_id,
            name=args.origin_host,
            type="A",
            ttl=60,
            records=[args.origin_ip],
            allow_overwrite=True,
            opts=child_opts,
        )

        outputs = {
            "apiUrl": pulumi.Output.concat("https://", args.api_host),
            "apiDistributionDomainName": self.distribution.domain_name,
            "apiDistributionId": self.distribution.id,
            "distributionBucketName": args.distribution_bucket_name,
            "originHost": args.origin_host,
        }
        for key, value in outputs.items():
            pulumi.export(key, value)
        self.register_outputs(outputs)
