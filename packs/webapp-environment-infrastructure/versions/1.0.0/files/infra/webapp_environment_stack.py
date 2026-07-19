"""Pulumi ComponentResource composing a webapp environment stack.

The origin EC2 box is provisioned by a separately applied standalone VPS stack
and consumed here through a Pulumi StackReference. Beyond composing that origin
with Aurora and the API edge, every environment carries the origin runtime
substrate unconditionally: a CloudWatch log group for the core
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
from dataclasses import dataclass, field
from typing import Optional

import pulumi
import pulumi_aws as aws

from webapp_api_stack import WebappApiArgs, WebappApiStack
from webapp_database_stack import (
    DEFAULT_SECONDS_UNTIL_AUTO_PAUSE,
    WebappDatabaseArgs,
    WebappDatabaseStack,
)
from webapp_environment_origin_policy import apply_input, origin_role_policy_json

_SSM_MANAGED_INSTANCE_CORE_POLICY_ARN = (
    "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
)


@dataclass
class WebappEnvironmentArgs:
    deploy_namespace: str
    environment: str
    domain_name: str
    api_host: str
    origin_host: str
    hosted_zone_id: str
    api_origin_port: int
    # Pulumi stack name of the standalone VPS stack serving as this
    # environment's origin.
    origin_vps_stack_name: str
    # Output names on the standalone VPS stack. The renderer supplies these
    # so their single authority remains its shared output-name constants.
    origin_vps_elastic_ip_output: str
    origin_vps_security_group_output: str
    database_name: str
    database_master_username: str
    database_engine_version: str
    database_min_capacity_acu: float
    database_max_capacity_acu: float
    database_backup_retention_days: int
    database_allowed_security_group_ids: list[str] = field(default_factory=list)
    distribution_bucket_name: str = ""
    distribution_origin_id: str = ""
    distribution_base_url: str = ""
    distribution_repository_variable_namespace: str = ""
    github_repo: str = ""
    github_api_url: str = "https://api.github.com"
    database_seconds_until_auto_pause: int = DEFAULT_SECONDS_UNTIL_AUTO_PAUSE
    # Name of the project's shared ECR repository the origin pulls images
    # from. Empty (default) composes ``f"{deploy_namespace}-core"`` — the same
    # default the registry stack's config applies.
    container_repository_name: str = ""
    # Wildcard preview domain for ephemeral environments hosted on this
    # environment's origin box. Empty (default) skips the wildcard DNS
    # record and the DNS-01 certificate-issuance role grants.
    ephemeral_preview_domain: str = ""
    github_app_private_key_secret_arn: str = ""
    github_app_kms_key_arn: str = ""


class WebappEnvironmentStack(pulumi.ComponentResource):
    """Compose origin runtime substrate, Aurora PostgreSQL, and API edge."""

    origin_vps: pulumi.StackReference
    database: WebappDatabaseStack
    api: WebappApiStack
    core_log_group: aws.cloudwatch.LogGroup
    origin_role: aws.iam.Role
    origin_instance_profile: aws.iam.InstanceProfile
    artifacts_bucket: aws.s3.BucketV2
    ephemeral_wildcard_record: Optional[aws.route53.Record]
    distribution_repository_variables: tuple[object, ...]

    def __init__(
        self,
        name: str,
        args: WebappEnvironmentArgs,
        opts: Optional[pulumi.ResourceOptions] = None,
    ) -> None:
        super().__init__("webapp:infra:WebappEnvironmentStack", name, None, opts)
        if args.github_app_kms_key_arn and not args.github_app_private_key_secret_arn:
            raise ValueError("github_app_kms_key_arn requires a GitHub App secret ARN")

        # Cost-allocation tags: project + environment on every env-bound
        # resource (the shared registry stack stays project-only).
        tags = {"project": args.deploy_namespace, "environment": args.environment}
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
            args.container_repository_name or f"{args.deploy_namespace}-core"
        )

        # --- Origin runtime substrate: log group + ECR-pull/logs role ---
        self.core_log_group = aws.cloudwatch.LogGroup(
            "coreLogGroup",
            name=f"/{args.deploy_namespace}/{args.environment}/core",
            retention_in_days=30,
            tags=tags,
            opts=child_opts,
        )

        # --- Per-environment artifacts bucket (QA evidence) ---
        # Private, deterministic name (recorded into environments.settings
        # .artifacts.bucket so the qa.artifact.presign resolver finds it),
        # 365-day expiry: run evidence is operational, not an archive.
        artifacts_bucket_name = f"{args.deploy_namespace}-{args.environment}-artifacts"
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
            "originSsmManagedInstancePolicy",
            role=self.origin_role.name,
            policy_arn=_SSM_MANAGED_INSTANCE_CORE_POLICY_ARN,
            opts=child_opts,
        )
        self.origin_instance_profile = aws.iam.InstanceProfile(
            "originInstanceProfile",
            role=self.origin_role.name,
            tags=tags,
            opts=child_opts,
        )

        self.origin_vps = pulumi.StackReference(args.origin_vps_stack_name)
        origin_ip = self.origin_vps.require_output(args.origin_vps_elastic_ip_output)
        origin_security_group_id = self.origin_vps.require_output(
            args.origin_vps_security_group_output
        )

        self.database = WebappDatabaseStack(
            "database",
            WebappDatabaseArgs(
                deploy_namespace=args.deploy_namespace,
                environment=args.environment,
                database_name=args.database_name,
                master_username=args.database_master_username,
                engine_version=args.database_engine_version,
                vpc_id=default_vpc.id,
                subnet_ids=default_subnets.ids,
                allowed_security_group_ids=[
                    origin_security_group_id,
                    *args.database_allowed_security_group_ids,
                ],
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
                lambda log_group_arn: apply_input(
                    self.database.master_secret_arn,
                    lambda database_secret_arn: origin_role_policy_json(
                        log_group_arn=log_group_arn,
                        repository_arn=repository_arn,
                        database_secret_arn=database_secret_arn,
                        github_app_private_key_secret_arn=(
                            args.github_app_private_key_secret_arn
                        ),
                        github_app_kms_key_arn=args.github_app_kms_key_arn,
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
                deploy_namespace=args.deploy_namespace,
                environment=args.environment,
                domain_name=args.domain_name,
                api_host=args.api_host,
                origin_host=args.origin_host,
                hosted_zone_id=args.hosted_zone_id,
                origin_ip=origin_ip,
                api_origin_port=args.api_origin_port,
                distribution_bucket_name=args.distribution_bucket_name,
                distribution_origin_id=args.distribution_origin_id,
            ),
            opts=child_opts,
        )
        self.distribution_repository_variables = ()
        if args.distribution_bucket_name:
            if not args.distribution_base_url:
                raise ValueError(
                    "distribution_base_url is required when distribution publishing is enabled"
                )
            if not args.github_repo:
                raise ValueError(
                    "github_repo is required when distribution publishing is enabled"
                )
            if not args.distribution_repository_variable_namespace:
                raise ValueError(
                    "distribution_repository_variable_namespace is required when "
                    "distribution publishing is enabled"
                )
            from webapp_distribution_github_variables import (
                create_distribution_variables,
            )

            self.distribution_repository_variables = create_distribution_variables(
                variable_namespace=args.distribution_repository_variable_namespace,
                environment=args.environment,
                github_repo=args.github_repo,
                github_api_url=args.github_api_url,
                base_url=args.distribution_base_url,
                bucket=args.distribution_bucket_name,
                cloudfront_id=self.api.distribution.id,
                origin_id=(
                    args.distribution_origin_id
                    or f"{args.deploy_namespace}-{args.environment}-distribution-static"
                ),
                child_opts=child_opts,
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
                records=[origin_ip],
                opts=child_opts,
            )

        outputs = {
            "environment": args.environment,
            "defaultVpcId": default_vpc.id,
            "defaultSubnetIds": default_subnets.ids,
            "originElasticIpAddress": origin_ip,
            "originSecurityGroupId": origin_security_group_id,
            "apiHost": args.api_host,
            "databaseClusterEndpoint": self.database.cluster.endpoint,
            "coreLogGroupName": self.core_log_group.name,
            "originInstanceProfileName": self.origin_instance_profile.name,
            "containerRepositoryName": container_repository_name,
            "artifactsBucketName": artifacts_bucket_name,
            "ephemeralPreviewDomain": args.ephemeral_preview_domain,
            "distributionRepositoryVariableNames": [
                variable.variable_name
                for variable in self.distribution_repository_variables
            ],
        }
        for key, value in outputs.items():
            pulumi.export(key, value)
        self.register_outputs(outputs)
