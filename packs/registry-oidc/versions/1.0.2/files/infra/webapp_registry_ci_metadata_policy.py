"""Metadata-only AWS reads required by rendered Pulumi resources."""

from __future__ import annotations

from collections.abc import Sequence


def metadata_read_statements(
    *,
    region: str,
    account_id: str,
    deploy_namespace: str,
    distribution_bucket_names: Sequence[str],
) -> list[dict[str, object]]:
    """Return metadata reads without secret or application-data access."""
    buckets = sorted({
        f"arn:aws:s3:::{deploy_namespace}-*",
        *(
            f"arn:aws:s3:::{str(name).strip()}"
            for name in distribution_bucket_names
            if str(name).strip()
        ),
    })
    return [
        {
            "Sid": "ReadGlobalInfrastructureMetadata",
            "Effect": "Allow",
            "Action": [
                "acm:DescribeCertificate", "acm:ListCertificates",
                "acm:ListTagsForCertificate", "autoscaling:Describe*",
                "cloudfront:DescribeFunction",
                "cloudfront:GetCloudFrontOriginAccessIdentity",
                "cloudfront:GetCloudFrontOriginAccessIdentityConfig",
                "cloudfront:GetDistribution", "cloudfront:GetDistributionConfig",
                "cloudfront:GetFunction", "cloudfront:ListTagsForResource",
                "ec2:Describe*", "events:DescribeRule",
                "events:ListTagsForResource", "events:ListTargetsByRule",
                "iam:GetOpenIDConnectProvider", "iam:ListOpenIDConnectProviders",
                "kms:ListAliases",
                "logs:DescribeLogGroups", "logs:ListTagsForResource",
                "rds:Describe*", "rds:ListTagsForResource",
                "route53:GetHostedZone", "route53:ListHostedZonesByName",
                "route53:ListResourceRecordSets", "route53:ListTagsForResource",
                "route53domains:GetDomainDetail",
                "route53domains:ListTagsForDomain", "ssm:DescribeParameters",
                "ssm:ListTagsForResource",
            ],
            "Resource": "*",
        },
        {
            "Sid": "ReadProjectIamMetadata",
            "Effect": "Allow",
            "Action": [
                "iam:GetInstanceProfile", "iam:GetRole", "iam:GetRolePolicy",
                "iam:ListAttachedRolePolicies",
                "iam:ListInstanceProfilesForRole", "iam:ListRolePolicies",
                "iam:ListRoleTags",
            ],
            "Resource": [
                f"arn:aws:iam::{account_id}:instance-profile/{deploy_namespace}-*",
                f"arn:aws:iam::{account_id}:role/{deploy_namespace}-*",
            ],
        },
        {
            "Sid": "ReadAttachedAwsPolicyMetadata",
            "Effect": "Allow",
            "Action": ["iam:GetPolicy", "iam:GetPolicyVersion"],
            "Resource": "arn:aws:iam::aws:policy/*",
        },
        {
            "Sid": "ReadProjectRepositoryMetadata",
            "Effect": "Allow",
            "Action": [
                "ecr:DescribeRepositories", "ecr:GetLifecyclePolicy",
                "ecr:GetRepositoryPolicy", "ecr:ListTagsForResource",
            ],
            "Resource": (
                f"arn:aws:ecr:{region}:{account_id}:"
                f"repository/{deploy_namespace}-*"
            ),
        },
        {
            "Sid": "ReadProjectFunctionMetadata",
            "Effect": "Allow",
            "Action": [
                "lambda:GetFunction", "lambda:GetFunctionCodeSigningConfig",
                "lambda:GetFunctionConcurrency", "lambda:GetFunctionConfiguration",
                "lambda:GetFunctionUrlConfig", "lambda:GetPolicy",
                "lambda:GetRuntimeManagementConfig", "lambda:ListTags",
                "lambda:ListVersionsByFunction",
            ],
            "Resource": (
                f"arn:aws:lambda:{region}:{account_id}:"
                f"function:{deploy_namespace}-*"
            ),
        },
        {
            "Sid": "ReadProjectBucketMetadata",
            "Effect": "Allow",
            "Action": [
                "s3:GetBucketAcl", "s3:GetBucketCors",
                "s3:GetBucketLifecycleConfiguration", "s3:GetBucketLocation",
                "s3:GetBucketLogging", "s3:GetBucketOwnershipControls",
                "s3:GetBucketPolicy", "s3:GetBucketPublicAccessBlock",
                "s3:GetBucketRequestPayment", "s3:GetBucketTagging",
                "s3:GetBucketVersioning", "s3:GetBucketWebsite", "s3:ListBucket",
            ],
            "Resource": buckets,
        },
        {
            "Sid": "ReadCanonicalUbuntuAmiParameter",
            "Effect": "Allow",
            "Action": "ssm:GetParameter",
            "Resource": (
                f"arn:aws:ssm:{region}::parameter/aws/service/canonical/"
                "ubuntu/server/24.04/stable/current/*"
            ),
        },
    ]


__all__ = ["metadata_read_statements"]
