# AUTO-GENERATED template source: templates/webapp/infra/webapp_environment_stack.py. Do not hand-edit rendered copies; refresh through Yoke template/onboarding surfaces.
"""Pulumi ComponentResource composing a webapp environment stack.

Beyond the VPS + Aurora + API edge composition, every environment carries the
origin runtime substrate unconditionally: a CloudWatch log group for the core
service, an EC2 instance profile whose role grants exactly ECR image pull
(from the project's shared container registry) + CloudWatch log shipping +
RDS-managed secret reads + scoped object access to the environment's artifacts
bucket, and a private
per-environment S3 artifacts bucket for durable evidence (QA screenshots and
similar run artifacts), exported as ``artifactsBucketName`` and recorded into
``environments.settings.artifacts.bucket``. The origin role also carries AWS
Session Manager's managed instance policy so operators have a provider-native
recovery path when SSH or the app runtime is unavailable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

import pulumi
import pulumi_aws as aws

from webapp_api_stack import WebappApiArgs, WebappApiStack
from webapp_database_stack import (
    DEFAULT_SECONDS_UNTIL_AUTO_PAUSE,
    WebappDatabaseArgs,
    WebappDatabaseStack,
)
from webapp_vps_stack import WebappVpsArgs, WebappVpsStack

_SSM_MANAGED_INSTANCE_CORE_POLICY_ARN = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"


def _apply_input(value, fn):
    apply = getattr(value, "apply", None)
    if callable(apply):
        return apply(fn)
    return fn(value)


def _origin_role_policy_json(
    *,
    log_group_arn: str,
    repository_arn: str,
    database_secret_arn: str,
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
            "Resource": [
                log_group_arn,
                f"{log_group_arn}:*",
            ],
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
            "Action": [
                "s3:PutObject",
                "s3:GetObject",
            ],
            "Resource": f"arn:aws:s3:::{artifacts_bucket_name}/*",
        },
    ]
    if include_preview_dns:
        statements += [
            {
                "Effect": "Allow",
                "Action": [
                    "route53:ListHostedZones",
                    "route53:GetChange",
                ],
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
        ]
    return json.dumps({"Version": "2012-10-17", "Statement": statements})


@dataclass
class WebappEnvironmentArgs:
    project_name: str
    environment: str
    stack_name: str
    domain_name: str
    api_host: str
    origin_host: str
    hosted_zone_id: str
    api_origin_port: int
    vps_instance_type: str
    vps_root_volume_gb: int
    vps_ssh_key_name: str
    database_name: str
    database_master_username: str
    database_engine_version: str
    database_min_capacity_acu: float
    database_max_capacity_acu: float
    database_backup_retention_days: int
    distribution_bucket_name: str = ""
    distribution_origin_id: str = ""
    database_seconds_until_auto_pause: int = DEFAULT_SECONDS_UNTIL_AUTO_PAUSE
    # Name of the project's shared ECR repository the origin pulls images
    # from. Empty (default) composes ``f"{project_name}-core"`` — the same
    # default the registry stack's config applies.
    container_repository_name: str = ""
    # Wildcard preview domain for ephemeral environments hosted on this
    # environment's origin box. Empty (default) skips the wildcard DNS
    # record and the DNS-01 certificate-issuance role grants.
    ephemeral_preview_domain: str = ""


class WebappEnvironmentStack(pulumi.ComponentResource):
    """Compose default-VPC EC2 origin, Aurora PostgreSQL, and API edge."""

    vps: WebappVpsStack
    database: WebappDatabaseStack
    api: WebappApiStack
    core_log_group: aws.cloudwatch.LogGroup
    origin_role: aws.iam.Role
    origin_instance_profile: aws.iam.InstanceProfile
    artifacts_bucket: aws.s3.BucketV2
    ephemeral_wildcard_record: Optional[aws.route53.Record]

    def __init__(
        self,
        name: str,
        args: WebappEnvironmentArgs,
        opts: Optional[pulumi.ResourceOptions] = None,
    ) -> None:
        super().__init__("webapp:infra:WebappEnvironmentStack", name, None, opts)

        # Cost-allocation tags: project + environment on every env-bound
        # resource (the shared registry stack stays project-only).
        tags = {"project": args.project_name, "environment": args.environment}
        child_opts = pulumi.ResourceOptions(parent=self)
        default_vpc = aws.ec2.get_vpc(default=True)
        default_subnets = aws.ec2.get_subnets(
            filters=[
                aws.ec2.GetSubnetsFilterArgs(
                    name="vpc-id",
                    values=[default_vpc.id],
                )
            ],
        )

        container_repository_name = (
            args.container_repository_name or f"{args.project_name}-core"
        )

        # --- Origin runtime substrate: log group + ECR-pull/logs role ---
        self.core_log_group = aws.cloudwatch.LogGroup(
            "coreLogGroup",
            name=f"/{args.project_name}/{args.environment}/core",
            retention_in_days=30,
            tags=tags,
            opts=child_opts,
        )

        # --- Per-environment artifacts bucket (QA evidence) ---
        # Private, deterministic name (recorded into environments.settings
        # .artifacts.bucket so the qa.artifact.presign resolver finds it),
        # 365-day expiry: run evidence is operational, not an archive.
        artifacts_bucket_name = f"{args.project_name}-{args.environment}-artifacts"
        self.artifacts_bucket = aws.s3.BucketV2(
            "artifactsBucket",
            bucket=artifacts_bucket_name,
            tags=tags,
            opts=child_opts,
        )
        aws.s3.BucketPublicAccessBlock(
            "artifactsBucketPublicAccessBlock",
            bucket=self.artifacts_bucket.id,
            block_public_acls=True,
            block_public_policy=True,
            ignore_public_acls=True,
            restrict_public_buckets=True,
            opts=child_opts,
        )
        aws.s3.BucketLifecycleConfigurationV2(
            "artifactsBucketLifecycle",
            bucket=self.artifacts_bucket.id,
            rules=[
                aws.s3.BucketLifecycleConfigurationV2RuleArgs(
                    id="expire-artifacts",
                    status="Enabled",
                    expiration=(
                        aws.s3.BucketLifecycleConfigurationV2RuleExpirationArgs(
                            days=365,
                        )
                    ),
                )
            ],
            opts=child_opts,
        )

        # Least-privilege inline policy facts: auth-token issuance is account-
        # wide by AWS design; image pulls are pinned to the project repository;
        # log writes are pinned to this environment's core log group. The
        # policy itself is created after the database so it can pin runtime DB
        # credential reads to the RDS-managed secret ARN.
        caller = aws.get_caller_identity()
        region = aws.get_region()
        repository_arn = (
            f"arn:aws:ecr:{region.name}:{caller.account_id}"
            f":repository/{container_repository_name}"
        )
        self.origin_role = aws.iam.Role(
            "originRole",
            assume_role_policy=json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": {"Service": "ec2.amazonaws.com"},
                            "Action": "sts:AssumeRole",
                        }
                    ],
                }
            ),
            tags=tags,
            opts=child_opts,
        )
        aws.iam.RolePolicyAttachment(
            "originSsmManagedInstancePolicy", role=self.origin_role.name,
            policy_arn=_SSM_MANAGED_INSTANCE_CORE_POLICY_ARN, opts=child_opts,
        )
        self.origin_instance_profile = aws.iam.InstanceProfile(
            "originInstanceProfile",
            role=self.origin_role.name,
            tags=tags,
            opts=child_opts,
        )

        self.vps = WebappVpsStack(
            "vps",
            WebappVpsArgs(
                project_name=args.project_name,
                environment=args.environment,
                instance_type=args.vps_instance_type,
                root_volume_gb=args.vps_root_volume_gb,
                ssh_key_name=args.vps_ssh_key_name,
                stack_name=args.stack_name,
                iam_instance_profile_name=self.origin_instance_profile.name,
            ),
            opts=child_opts,
        )

        self.database = WebappDatabaseStack(
            "database",
            WebappDatabaseArgs(
                project_name=args.project_name,
                environment=args.environment,
                database_name=args.database_name,
                master_username=args.database_master_username,
                engine_version=args.database_engine_version,
                vpc_id=default_vpc.id,
                subnet_ids=default_subnets.ids,
                allowed_security_group_ids=[self.vps.security_group.id],
                min_capacity=args.database_min_capacity_acu,
                max_capacity=args.database_max_capacity_acu,
                backup_retention_days=args.database_backup_retention_days,
                seconds_until_auto_pause=args.database_seconds_until_auto_pause,
            ),
            opts=child_opts,
        )
        aws.iam.RolePolicy(
            "originRolePolicy",
            role=self.origin_role.id,
            policy=self.core_log_group.arn.apply(
                lambda log_group_arn: _apply_input(
                    self.database.master_secret_arn,
                    lambda database_secret_arn: _origin_role_policy_json(
                        log_group_arn=log_group_arn,
                        repository_arn=repository_arn,
                        database_secret_arn=database_secret_arn,
                        artifacts_bucket_name=artifacts_bucket_name,
                        hosted_zone_id=args.hosted_zone_id,
                        include_preview_dns=bool(args.ephemeral_preview_domain),
                    ),
                )
            ),
            opts=child_opts,
        )

        self.api = WebappApiStack(
            "api",
            WebappApiArgs(
                project_name=args.project_name,
                environment=args.environment,
                domain_name=args.domain_name,
                api_host=args.api_host,
                origin_host=args.origin_host,
                hosted_zone_id=args.hosted_zone_id,
                origin_ip=self.vps.elastic_ip.public_ip,
                api_origin_port=args.api_origin_port,
                distribution_bucket_name=args.distribution_bucket_name,
                distribution_origin_id=args.distribution_origin_id,
            ),
            opts=child_opts,
        )

        # Wildcard preview DNS: every <branch-slug>.<preview_domain> resolves
        # straight to this environment's origin box.
        self.ephemeral_wildcard_record = None
        if args.ephemeral_preview_domain:
            self.ephemeral_wildcard_record = aws.route53.Record(
                "ephemeralWildcardRecord",
                zone_id=args.hosted_zone_id,
                name=f"*.{args.ephemeral_preview_domain}",
                type="A",
                ttl=300,
                records=[self.vps.elastic_ip.public_ip],
                opts=child_opts,
            )

        outputs = {
            "environment": args.environment,
            "defaultVpcId": default_vpc.id,
            "defaultSubnetIds": default_subnets.ids,
            "originElasticIpAddress": self.vps.elastic_ip.public_ip,
            "originSecurityGroupId": self.vps.security_group.id,
            "apiHost": args.api_host,
            "databaseClusterEndpoint": self.database.cluster.endpoint,
            "coreLogGroupName": self.core_log_group.name,
            "originInstanceProfileName": self.origin_instance_profile.name,
            "containerRepositoryName": container_repository_name,
            "artifactsBucketName": artifacts_bucket_name,
            "ephemeralPreviewDomain": args.ephemeral_preview_domain,
        }
        for key, value in outputs.items():
            pulumi.export(key, value)
        self.register_outputs(outputs)
