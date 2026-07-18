# AUTO-GENERATED template source: templates/webapp/infra/webapp_registry_ci_policy.py. Do not hand-edit rendered copies; refresh through Yoke template/onboarding surfaces.
"""Least-privilege AWS delivery policy for GitHub Actions."""

from __future__ import annotations

import json
from collections.abc import Sequence


def github_app_private_key_deny_statement(
    *,
    region: str,
    account_id: str,
    secret_arns: Sequence[str],
) -> dict[str, object]:
    denied_secrets = sorted(
        {
            *(str(arn).strip() for arn in secret_arns if str(arn).strip()),
            (
                f"arn:aws:secretsmanager:{region}:{account_id}:"
                "secret:*github-app-private-key-*"
            ),
        }
    )
    return {
        "Sid": "DenyGitHubAppPrivateKeys",
        "Effect": "Deny",
        "Action": [
            "secretsmanager:BatchGetSecretValue",
            "secretsmanager:DescribeSecret",
            "secretsmanager:GetSecretValue",
        ],
        "Resource": denied_secrets,
    }


def _pulumi_state_read_statements(
    *,
    state_bucket: str,
    kms_key_arn: str,
) -> list[dict[str, object]]:
    return [
        {
            "Sid": "ReadPulumiStateBucketLocation",
            "Effect": "Allow",
            "Action": "s3:GetBucketLocation",
            "Resource": f"arn:aws:s3:::{state_bucket}",
        },
        {
            "Sid": "ListPulumiState",
            "Effect": "Allow",
            "Action": "s3:ListBucket",
            "Resource": f"arn:aws:s3:::{state_bucket}",
            "Condition": {
                "StringLike": {"s3:prefix": [".pulumi", ".pulumi/*"]},
            },
        },
        {
            "Sid": "ReadPulumiStateObjects",
            "Effect": "Allow",
            "Action": "s3:GetObject",
            "Resource": f"arn:aws:s3:::{state_bucket}/.pulumi/*",
        },
        {
            "Sid": "DecryptPulumiStateDataKey",
            "Effect": "Allow",
            "Action": ["kms:Decrypt", "kms:DescribeKey"],
            "Resource": kms_key_arn,
        },
    ]


def infrastructure_preview_policy_json(
    *,
    region: str,
    account_id: str,
    state_bucket: str,
    kms_key_arn: str,
    deploy_namespace: str,
    distribution_bucket_names: Sequence[str],
    github_app_private_key_secret_arns: Sequence[str],
) -> str:
    """Add exact state reads and immutable custody guards to ViewOnlyAccess."""
    statements = _pulumi_state_read_statements(
        state_bucket=state_bucket,
        kms_key_arn=kms_key_arn,
    )
    from webapp_registry_ci_metadata_policy import metadata_read_statements

    statements.extend(
        metadata_read_statements(
            region=region,
            account_id=account_id,
            deploy_namespace=deploy_namespace,
            distribution_bucket_names=distribution_bucket_names,
        )
    )
    statements.extend(
        [
            {
                "Sid": "DenySecretValues",
                "Effect": "Deny",
                "Action": [
                    "secretsmanager:BatchGetSecretValue",
                    "secretsmanager:GetSecretValue",
                ],
                "Resource": "*",
            },
            {
                "Sid": "DenyNonStateObjectReads",
                "Effect": "Deny",
                "Action": ["s3:GetObject", "s3:GetObjectVersion"],
                "NotResource": f"arn:aws:s3:::{state_bucket}/.pulumi/*",
            },
            {
                "Sid": "DenyNonPublicParameterValues",
                "Effect": "Deny",
                "Action": [
                    "ssm:GetParameter",
                    "ssm:GetParameterHistory",
                    "ssm:GetParameters",
                    "ssm:GetParametersByPath",
                ],
                "NotResource": (
                    f"arn:aws:ssm:{region}::parameter/aws/service/canonical/"
                    "ubuntu/server/24.04/stable/current/*"
                ),
            },
            {
                "Sid": "DenyPrivilegeEscalation",
                "Effect": "Deny",
                "Action": [
                    "iam:Add*",
                    "iam:Attach*",
                    "iam:Create*",
                    "iam:Delete*",
                    "iam:Detach*",
                    "iam:PassRole",
                    "iam:Put*",
                    "iam:Remove*",
                    "iam:Set*",
                    "iam:Tag*",
                    "iam:Untag*",
                    "iam:Update*",
                    "iam:Upload*",
                    "organizations:*",
                    "sts:AssumeRole",
                ],
                "Resource": "*",
            },
            github_app_private_key_deny_statement(
                region=region,
                account_id=account_id,
                secret_arns=github_app_private_key_secret_arns,
            ),
        ]
    )
    return json.dumps({"Version": "2012-10-17", "Statement": statements})


def delivery_policy_json(
    *,
    region: str,
    account_id: str,
    deploy_namespace: str,
    state_bucket: str,
    kms_key_arn: str,
    distribution_bucket_names: Sequence[str],
    cloudfront_distribution_ids: Sequence[str],
    github_app_private_key_secret_arns: Sequence[str],
) -> str:
    """Allow delivery operations while denying every known App-key secret."""
    repository_arn = (
        f"arn:aws:ecr:{region}:{account_id}:repository/{deploy_namespace}-*"
    )
    statements: list[dict[str, object]] = [
        {
            "Sid": "EcrLogin",
            "Effect": "Allow",
            "Action": "ecr:GetAuthorizationToken",
            "Resource": "*",
        },
        {
            "Sid": "ProjectImageDelivery",
            "Effect": "Allow",
            "Action": [
                "ecr:BatchCheckLayerAvailability",
                "ecr:BatchGetImage",
                "ecr:CompleteLayerUpload",
                "ecr:DescribeImages",
                "ecr:GetDownloadUrlForLayer",
                "ecr:InitiateLayerUpload",
                "ecr:PutImage",
                "ecr:UploadLayerPart",
            ],
            "Resource": repository_arn,
        },
        {
            "Sid": "DiscoverControlPlaneDatabase",
            "Effect": "Allow",
            "Action": "rds:DescribeDBClusters",
            "Resource": "*",
        },
        {
            "Sid": "DiscoverProjectOrigins",
            "Effect": "Allow",
            "Action": "ec2:DescribeInstances",
            "Resource": "*",
        },
        {
            "Sid": "StartProjectOrigins",
            "Effect": "Allow",
            "Action": "ec2:StartInstances",
            "Resource": (f"arn:aws:ec2:{region}:{account_id}:instance/*"),
            "Condition": {
                "StringEquals": {
                    "aws:ResourceTag/project": deploy_namespace,
                },
            },
        },
        {
            "Sid": "ReadRdsManagedDatabaseCredentials",
            "Effect": "Allow",
            "Action": [
                "secretsmanager:DescribeSecret",
                "secretsmanager:GetSecretValue",
            ],
            "Resource": (
                f"arn:aws:secretsmanager:{region}:{account_id}:secret:rds!cluster-*"
            ),
            "Condition": {
                "StringEquals": {
                    "secretsmanager:ResourceTag/"
                    "aws:secretsmanager:owningService": "rds",
                },
                "StringLike": {
                    "secretsmanager:ResourceTag/aws:rds:primaryDBClusterArn": (
                        f"arn:aws:rds:{region}:{account_id}:cluster:"
                        f"{deploy_namespace}-*-aurora"
                    ),
                },
            },
        },
    ]
    statements.extend(
        _pulumi_state_read_statements(
            state_bucket=state_bucket,
            kms_key_arn=kms_key_arn,
        )
    )
    buckets = sorted(
        {str(name).strip() for name in distribution_bucket_names if str(name).strip()}
    )
    distribution_ids = sorted(
        {
            str(distribution_id).strip()
            for distribution_id in cloudfront_distribution_ids
            if str(distribution_id).strip()
        }
    )
    if buckets:
        statements.extend(
            [
                {
                    "Sid": "ListDistributionBuckets",
                    "Effect": "Allow",
                    "Action": ["s3:GetBucketLocation", "s3:ListBucket"],
                    "Resource": [f"arn:aws:s3:::{name}" for name in buckets],
                },
                {
                    "Sid": "PublishDistributionArtifacts",
                    "Effect": "Allow",
                    "Action": ["s3:GetObject", "s3:PutObject"],
                    "Resource": [f"arn:aws:s3:::{name}/*" for name in buckets],
                },
            ]
        )
    if distribution_ids:
        invalidation_resources = [
            f"arn:aws:cloudfront::{account_id}:distribution/{distribution_id}"
            for distribution_id in distribution_ids
        ]
        statements.extend(
            [
                {
                    "Sid": "DiscoverDistributionIds",
                    "Effect": "Allow",
                    "Action": "cloudfront:ListDistributions",
                    "Resource": "*",
                },
                {
                    "Sid": "InvalidateProjectDistributions",
                    "Effect": "Allow",
                    "Action": "cloudfront:CreateInvalidation",
                    "Resource": invalidation_resources,
                },
            ]
        )
    statements.append(
        github_app_private_key_deny_statement(
            region=region,
            account_id=account_id,
            secret_arns=github_app_private_key_secret_arns,
        )
    )
    return json.dumps({"Version": "2012-10-17", "Statement": statements})


__all__ = [
    "delivery_policy_json",
    "github_app_private_key_deny_statement",
    "infrastructure_preview_policy_json",
]
