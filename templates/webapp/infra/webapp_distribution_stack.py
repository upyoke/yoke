# AUTO-GENERATED template source: templates/webapp/infra/webapp_distribution_stack.py. Do not hand-edit rendered copies; refresh through Yoke template/onboarding surfaces.
"""Optional static distribution origin for public installer artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

import pulumi
import pulumi_aws as aws

# PEP 503 clients request directory URLs (``/simple/<project>/``); the S3/OAI
# origin does not serve a directory index, so a viewer-request function rewrites
# a trailing-slash URI to the stored ``index.html`` object at the edge.
_SIMPLE_INDEX_REWRITE_CODE = """\
function handler(event) {
    var request = event.request;
    if (request.uri.endsWith('/')) {
        request.uri += 'index.html';
    }
    return request;
}
"""


@dataclass
class WebappDistributionHosting:
    """Resources and CloudFront args contributed by distribution hosting."""

    origins: list[object]
    ordered_cache_behaviors: list[object]
    bucket: Optional[aws.s3.BucketV2]
    origin_access_identity_arn: Optional[object]


def build_distribution_hosting(
    *,
    project_name: str,
    distribution_bucket_name: str,
    distribution_origin_id: str,
    app_origin: object,
    tags: dict[str, str],
    child_opts: pulumi.ResourceOptions,
) -> WebappDistributionHosting:
    origins = [app_origin]
    ordered_cache_behaviors = []
    bucket = None

    if not distribution_bucket_name:
        return WebappDistributionHosting(
            origins=origins,
            ordered_cache_behaviors=ordered_cache_behaviors,
            bucket=bucket,
            origin_access_identity_arn=None,
        )

    bucket = aws.s3.BucketV2(
        "distributionBucket",
        bucket=distribution_bucket_name,
        tags=tags,
        opts=child_opts,
    )
    aws.s3.BucketPublicAccessBlock(
        "distributionBucketPublicAccessBlock",
        bucket=bucket.id,
        block_public_acls=True,
        block_public_policy=True,
        ignore_public_acls=True,
        restrict_public_buckets=True,
        opts=child_opts,
    )
    origin_access = aws.cloudfront.OriginAccessIdentity(
        "distributionOriginAccess",
        comment=f"{distribution_origin_id} read access",
        opts=child_opts,
    )
    origins.append(
        aws.cloudfront.DistributionOriginArgs(
            origin_id=distribution_origin_id,
            domain_name=bucket.bucket_regional_domain_name,
            s3_origin_config=aws.cloudfront.DistributionOriginS3OriginConfigArgs(
                origin_access_identity=origin_access.cloudfront_access_identity_path,
            ),
        )
    )
    simple_index_rewrite = aws.cloudfront.Function(
        "distributionSimpleIndexRewrite",
        # CloudFront Functions are account-global; key the name on the per-env
        # distribution bucket so stage and prod do not collide. An in-use
        # function cannot be renamed (CloudFront returns FunctionInUse), so the
        # name is fixed at create time and later name drift is ignored.
        name=f"{distribution_bucket_name}-simple-index",
        runtime="cloudfront-js-2.0",
        comment=f"{project_name}: serve index.html for PEP 503 simple/ directory URLs",
        code=_SIMPLE_INDEX_REWRITE_CODE,
        publish=True,
        opts=pulumi.ResourceOptions.merge(
            child_opts, pulumi.ResourceOptions(ignore_changes=["name"])
        ),
    )
    for path_pattern in ("install", "dist/*", "simple/*"):
        behavior = dict(
            path_pattern=path_pattern,
            target_origin_id=distribution_origin_id,
            viewer_protocol_policy="redirect-to-https",
            compress=True,
            allowed_methods=["GET", "HEAD", "OPTIONS"],
            cached_methods=["GET", "HEAD"],
            cache_policy_id="658327ea-f89d-4fab-a63d-7e88639e58f6",
        )
        if path_pattern == "simple/*":
            behavior["function_associations"] = [
                aws.cloudfront.DistributionOrderedCacheBehaviorFunctionAssociationArgs(
                    event_type="viewer-request",
                    function_arn=simple_index_rewrite.arn,
                )
            ]
        ordered_cache_behaviors.append(
            aws.cloudfront.DistributionOrderedCacheBehaviorArgs(**behavior)
        )
    return WebappDistributionHosting(
        origins=origins,
        ordered_cache_behaviors=ordered_cache_behaviors,
        bucket=bucket,
        origin_access_identity_arn=origin_access.iam_arn,
    )


def attach_distribution_bucket_policy(
    *,
    bucket: aws.s3.BucketV2,
    bucket_name: str,
    origin_access_identity_arn: object,
    child_opts: pulumi.ResourceOptions,
) -> aws.s3.BucketPolicy:
    return aws.s3.BucketPolicy(
        "distributionBucketPolicy",
        bucket=bucket.id,
        policy=origin_access_identity_arn.apply(
            lambda arn: json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Sid": "AllowCloudFrontRead",
                            "Effect": "Allow",
                            "Principal": {
                                "AWS": arn,
                            },
                            "Action": "s3:GetObject",
                            "Resource": f"arn:aws:s3:::{bucket_name}/*",
                        }
                    ],
                },
                sort_keys=True,
            )
        ),
        opts=child_opts,
    )
