# AUTO-GENERATED template source: templates/webapp/infra/webapp_infra_stack.py. Do not hand-edit rendered copies; refresh through Yoke template/onboarding surfaces.
"""Pulumi ComponentResource for the webapp public-edge stack.

Provisions:
- CloudFront distribution with HTTP VPS origin
- A and AAAA alias records pointing to CloudFront (apex + www)
- www-to-apex redirect via CloudFront Function

Pre-existing Route 53 zone and ACM certificate are imported via config inputs
(``hosted_zone_id`` and ``certificate_arn``); this stack never creates them.
That import-only boundary is the safety property that lets the prod cutover
preserve live DNS and TLS state.

All 4 URL variants resolve to https://apex:
    http://apex       -> 301 -> https://apex  (CloudFront viewer protocol)
    https://apex      -> served directly
    http://www.apex   -> 301 -> https://apex  (viewer protocol + CF Function)
    https://www.apex  -> 301 -> https://apex  (CF Function)
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

# CloudFront Function JS body. Keep byte-stable so the AWS-side function
# source is byte-equivalent post-import.
_WWW_REDIRECT_FUNCTION_CODE = """
function handler(event) {
  var request = event.request;
  var host = request.headers.host.value;
  if (host.startsWith('www.')) {
    var apex = host.substring(4);
    var uri = request.uri;
    var qs = Object.keys(request.querystring).length > 0
      ? '?' + Object.keys(request.querystring).map(function(k) {
          var v = request.querystring[k];
          return v.multiValue
            ? v.multiValue.map(function(mv) { return k + '=' + mv.value; }).join('&')
            : k + '=' + v.value;
        }).join('&')
      : '';
    return {
      statusCode: 301,
      statusDescription: 'Moved Permanently',
      headers: {
        location: { value: 'https://' + apex + uri + qs }
      }
    };
  }
  return request;
}
"""


@dataclass
class WebappInfraArgs:
    """Inputs for ``WebappInfraStack``."""

    domain_name: str
    origin_host: str
    project_name: str
    hosted_zone_id: str
    certificate_arn: str
    # CloudFront origin Id. Must equal the live distribution's origin Id
    # for ``pulumi import`` to land a zero-change diff against existing
    # imported distributions. Required so each project explicitly pins
    # the value in DB-backed renderer settings rather than inheriting any
    # other project's historical logical-id form. Fresh stacks may use
    # any stable string.
    origin_id: str
    # Optional static distribution bucket for public install artifacts. When
    # set, the stack adds an S3 origin and routes /install plus /dist/* to it.
    distribution_bucket_name: str = ""
    distribution_origin_id: str = "yoke-distribution-static"
    domain_txt_records: Sequence[DomainTxtRecordArgs] = ()
    domain_mx_records: Sequence[DomainMxRecordArgs] = ()


class WebappInfraStack(pulumi.ComponentResource):
    """CloudFront + Route 53 alias records, fronting a single HTTP origin."""

    distribution: aws.cloudfront.Distribution
    www_redirect_function: aws.cloudfront.Function
    hosted_zone: aws.route53.GetZoneResult
    certificate: aws.acm.GetCertificateResult

    def __init__(
        self,
        name: str,
        args: WebappInfraArgs,
        opts: Optional[pulumi.ResourceOptions] = None,
    ) -> None:
        # Pulumi tracks ComponentResources by URN, which embeds the type
        # string. The alias on the old ``buzz:infra:BuzzInfraStack`` type
        # tells Pulumi that the renamed component is the same resource —
        # without it, ``pulumi up`` against an existing stack would propose
        # to destroy the old ComponentResource (and all its children) and
        # create a new one, which would destroy live infrastructure.
        super().__init__(
            "webapp:infra:WebappInfraStack",
            name,
            None,
            pulumi.ResourceOptions.merge(
                opts,
                pulumi.ResourceOptions(
                    aliases=[pulumi.Alias(type_="buzz:infra:BuzzInfraStack")],
                ),
            ),
        )

        tags = {"project": args.project_name}
        child_opts = pulumi.ResourceOptions(parent=self)

        # --- Route 53 hosted zone (import-only) ---
        self.hosted_zone = aws.route53.get_zone(zone_id=args.hosted_zone_id)

        # --- ACM certificate (import-only). Certs in us-east-1 are required by
        # CloudFront; lookup is unambiguous when statuses=["ISSUED"]. ---
        self.certificate = aws.acm.get_certificate(
            domain=args.domain_name,
            statuses=["ISSUED"],
            most_recent=True,
        )
        certificate_arn = args.certificate_arn or self.certificate.arn

        # --- CloudFront Function: www-to-apex redirect ---
        # Explicit ``name=`` pins the AWS-side name so ``pulumi import`` can
        # address it; without this, Pulumi would derive a URN-based name that
        # would not match the live ``buzz-www-redirect`` function.
        # ``publish=False`` is set explicitly so zero-change cutover from
        # the live function holds: the historical IaC runtime published
        # implicitly on every synth, but ``pulumi import`` captured the
        # imported state with ``publish: null``. The
        # ``terraform-aws-provider`` resource declares ``publish`` as an
        # optional bool that defaults to ``True`` when unset, so omitting
        # it would re-publish the function on every ``pulumi up``.
        # Future operator-driven re-publish is a manual
        # ``aws cloudfront publish-function`` step, surfaced in the
        # project's ops/DEPLOY runbook.
        self.www_redirect_function = aws.cloudfront.Function(
            "wwwRedirectFunction",
            name=f"{args.project_name}-www-redirect",
            runtime="cloudfront-js-2.0",
            comment=f"{args.project_name}: redirect www to apex domain",
            code=_WWW_REDIRECT_FUNCTION_CODE,
            publish=False,
            opts=child_opts,
        )

        from webapp_distribution_stack import build_distribution_hosting

        app_origin = aws.cloudfront.DistributionOriginArgs(
            origin_id=args.origin_id,
            domain_name=args.origin_host,
            custom_origin_config=aws.cloudfront.DistributionOriginCustomOriginConfigArgs(
                http_port=80,
                https_port=443,
                origin_protocol_policy="http-only",
                origin_ssl_protocols=["TLSv1.2"],
            ),
            custom_headers=[
                aws.cloudfront.DistributionOriginCustomHeaderArgs(
                    name="X-Forwarded-Host",
                    value=args.domain_name,
                ),
            ],
        )
        distribution_hosting = build_distribution_hosting(
            project_name=args.project_name,
            distribution_bucket_name=args.distribution_bucket_name,
            distribution_origin_id=args.distribution_origin_id,
            app_origin=app_origin,
            tags=tags,
            child_opts=child_opts,
        )
        self.distribution_bucket = distribution_hosting.bucket
        self.distribution_bucket_policy = None

        # --- CloudFront Distribution ---
        self.distribution = aws.cloudfront.Distribution(
            "distribution",
            enabled=True,
            is_ipv6_enabled=True,
            comment=f"{args.project_name} CDN",
            http_version="http2and3",
            aliases=[args.domain_name, f"www.{args.domain_name}"],
            origins=distribution_hosting.origins,
            ordered_cache_behaviors=distribution_hosting.ordered_cache_behaviors,
            default_cache_behavior=aws.cloudfront.DistributionDefaultCacheBehaviorArgs(
                target_origin_id=args.origin_id,
                viewer_protocol_policy="redirect-to-https",
                # Matches the live distribution which has compression on;
                # zero-change cutover relies on this alignment.
                compress=True,
                # AWS-managed policies. CachingDisabled =
                # 4135ea2d-6df8-44a3-9df3-4b5a84be39ad; AllViewer (origin
                # request) = 216adef6-5c7f-47e4-b989-5492eafa07d3.
                cache_policy_id="4135ea2d-6df8-44a3-9df3-4b5a84be39ad",
                origin_request_policy_id="216adef6-5c7f-47e4-b989-5492eafa07d3",
                allowed_methods=[
                    "GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE",
                ],
                cached_methods=["GET", "HEAD"],
                function_associations=[
                    aws.cloudfront.DistributionDefaultCacheBehaviorFunctionAssociationArgs(
                        event_type="viewer-request",
                        function_arn=self.www_redirect_function.arn,
                    ),
                ],
            ),
            viewer_certificate=aws.cloudfront.DistributionViewerCertificateArgs(
                acm_certificate_arn=certificate_arn,
                ssl_support_method="sni-only",
                minimum_protocol_version="TLSv1.2_2021",
            ),
            restrictions=aws.cloudfront.DistributionRestrictionsArgs(
                geo_restriction=aws.cloudfront.DistributionRestrictionsGeoRestrictionArgs(
                    restriction_type="none",
                ),
            ),
            tags=tags,
            opts=child_opts,
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

        # --- Route 53 alias records pointing at the CloudFront distribution ---
        # Z2FDTNDATAQYW2 is CloudFront's fixed hosted zone id for alias
        # targets; the constant is documented in the AWS Route 53 reference.
        cf_alias_zone_id = "Z2FDTNDATAQYW2"

        aws.route53.Record(
            "apexA",
            zone_id=args.hosted_zone_id,
            name=args.domain_name,
            type="A",
            aliases=[
                aws.route53.RecordAliasArgs(
                    name=self.distribution.domain_name,
                    zone_id=cf_alias_zone_id,
                    evaluate_target_health=False,
                ),
            ],
            opts=child_opts,
        )
        aws.route53.Record(
            "apexAAAA",
            zone_id=args.hosted_zone_id,
            name=args.domain_name,
            type="AAAA",
            aliases=[
                aws.route53.RecordAliasArgs(
                    name=self.distribution.domain_name,
                    zone_id=cf_alias_zone_id,
                    evaluate_target_health=False,
                ),
            ],
            opts=child_opts,
        )
        aws.route53.Record(
            "wwwA",
            zone_id=args.hosted_zone_id,
            name=f"www.{args.domain_name}",
            type="A",
            aliases=[
                aws.route53.RecordAliasArgs(
                    name=self.distribution.domain_name,
                    zone_id=cf_alias_zone_id,
                    evaluate_target_health=False,
                ),
            ],
            opts=child_opts,
        )
        aws.route53.Record(
            "wwwAAAA",
            zone_id=args.hosted_zone_id,
            name=f"www.{args.domain_name}",
            type="AAAA",
            aliases=[
                aws.route53.RecordAliasArgs(
                    name=self.distribution.domain_name,
                    zone_id=cf_alias_zone_id,
                    evaluate_target_health=False,
                ),
            ],
            opts=child_opts,
        )
        create_domain_txt_records(
            domain_name=args.domain_name,
            hosted_zone_id=args.hosted_zone_id,
            records=args.domain_txt_records,
            opts=child_opts,
        )
        create_domain_mx_records(
            domain_name=args.domain_name,
            hosted_zone_id=args.hosted_zone_id,
            records=args.domain_mx_records,
            opts=child_opts,
        )

        # --- Exports for downstream cutover scripts ---
        pulumi.export("distributionDomainName", self.distribution.domain_name)
        pulumi.export("distributionId", self.distribution.id)
        pulumi.export("hostedZoneId", args.hosted_zone_id)
        pulumi.export("distributionBucketName", args.distribution_bucket_name)

        self.register_outputs(
            {
                "distributionDomainName": self.distribution.domain_name,
                "distributionId": self.distribution.id,
                "hostedZoneId": args.hosted_zone_id,
                "distributionBucketName": args.distribution_bucket_name,
            }
        )
