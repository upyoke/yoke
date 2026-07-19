"""Least-privilege IAM policy for a webapp environment origin host."""

from __future__ import annotations

import json


def apply_input(value, fn):
    apply = getattr(value, "apply", None)
    if callable(apply):
        return apply(fn)
    return fn(value)


def origin_role_policy_json(
    *,
    log_group_arn: str,
    repository_arn: str,
    database_secret_arn: str,
    github_app_private_key_secret_arn: str,
    github_app_kms_key_arn: str,
    artifacts_bucket_name: str,
    hosted_zone_id: str,
    include_preview_dns: bool,
) -> str:
    statements = [
        {
            "Effect": "Allow",
            "Action": ["ecr:GetAuthorizationToken"],
            "Resource": "*",
        },
        {
            "Effect": "Allow",
            "Action": [
                "ecr:BatchGetImage",
                "ecr:GetDownloadUrlForLayer",
                "ecr:BatchCheckLayerAvailability",
            ],
            "Resource": repository_arn,
        },
        {
            "Effect": "Allow",
            "Action": [
                "logs:CreateLogStream",
                "logs:PutLogEvents",
                "logs:DescribeLogStreams",
            ],
            "Resource": [log_group_arn, f"{log_group_arn}:*"],
        },
        {
            "Effect": "Allow",
            "Action": [
                "secretsmanager:DescribeSecret",
                "secretsmanager:GetSecretValue",
            ],
            "Resource": database_secret_arn,
        },
        {
            "Effect": "Allow",
            "Action": ["s3:PutObject", "s3:GetObject"],
            "Resource": f"arn:aws:s3:::{artifacts_bucket_name}/*",
        },
    ]
    if github_app_private_key_secret_arn:
        statements.append({
            "Sid": "ReadEnvironmentGitHubAppPrivateKey",
            "Effect": "Allow",
            "Action": [
                "secretsmanager:DescribeSecret",
                "secretsmanager:GetSecretValue",
            ],
            "Resource": github_app_private_key_secret_arn,
        })
    if github_app_kms_key_arn:
        statements.append({
            "Sid": "DecryptEnvironmentGitHubAppPrivateKey",
            "Effect": "Allow",
            "Action": ["kms:Decrypt", "kms:DescribeKey"],
            "Resource": github_app_kms_key_arn,
        })
    if include_preview_dns:
        statements.extend([
            {
                "Effect": "Allow",
                "Action": ["route53:ListHostedZones", "route53:GetChange"],
                "Resource": "*",
            },
            {
                "Effect": "Allow",
                "Action": [
                    "route53:ChangeResourceRecordSets",
                    "route53:ListResourceRecordSets",
                ],
                "Resource": f"arn:aws:route53:::hostedzone/{hosted_zone_id}",
            },
        ])
    return json.dumps({"Version": "2012-10-17", "Statement": statements})


__all__ = ["apply_input", "origin_role_policy_json"]
