# AUTO-GENERATED template source: templates/webapp/infra/webapp_database_stack.py. Do not hand-edit rendered copies; refresh through Yoke template/onboarding surfaces.
"""Pulumi ComponentResource for a webapp Aurora PostgreSQL database.

The component is deliberately project-generic. Callers pass the VPC, subnet,
and allowed origin security groups from their environment stack; this module
does not read stack config or any project-local context file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional, Sequence

import pulumi
import pulumi_aws as aws
import pulumi.dynamic as dynamic

_POSTGRES_PORT = 5432
DEFAULT_SECONDS_UNTIL_AUTO_PAUSE = 1800
_MIN_SECONDS_UNTIL_AUTO_PAUSE = 300
_MAX_SECONDS_UNTIL_AUTO_PAUSE = 86400
_ZERO_ACU_MINIMUMS = {13: 15, 14: 12, 15: 7, 16: 3}
_ZERO_ACU_GUIDANCE = (
    "min_capacity=0 enables Aurora Serverless v2 auto-pause, but AWS only "
    "documents the 0-256 ACU range for Aurora PostgreSQL 13.15+, 14.12+, "
    "15.7+, or 16.3+. Choose one of those engine_version families in the "
    "target region, or raise min_capacity above 0."
)
_ENGINE_VERSION_RE = re.compile(r"(\d+)\.(\d+)")
_IDENTIFIER_CLEANUP_RE = re.compile(r"[^a-z0-9-]+")
_DATABASE_INGRESS_DESCRIPTION = "PostgreSQL from caller-provided origin security groups"


@dataclass
class WebappDatabaseArgs:
    """Inputs for ``WebappDatabaseStack``."""

    deploy_namespace: str
    environment: str
    database_name: str
    master_username: str
    engine_version: str
    vpc_id: str
    subnet_ids: list[str]
    allowed_security_group_ids: list[str]
    min_capacity: float
    max_capacity: float
    backup_retention_days: int
    seconds_until_auto_pause: int = DEFAULT_SECONDS_UNTIL_AUTO_PAUSE


def _parse_engine_version(engine_version: str) -> tuple[int, int]:
    match = _ENGINE_VERSION_RE.search(engine_version.strip())
    if not match:
        raise pulumi.RunError(
            f"Unsupported Aurora PostgreSQL engine_version '{engine_version}'. "
            f"{_ZERO_ACU_GUIDANCE}"
        )
    return int(match.group(1)), int(match.group(2))


def _supports_zero_acu(engine_version: str) -> bool:
    major, minor = _parse_engine_version(engine_version)
    minimum_minor = _ZERO_ACU_MINIMUMS.get(major)
    return minimum_minor is not None and minor >= minimum_minor


def _validate_args(args: WebappDatabaseArgs) -> None:
    if not args.subnet_ids:
        raise pulumi.RunError("WebappDatabaseStack requires at least one subnet_id.")
    if not _deduplicated_security_group_ids(args.allowed_security_group_ids):
        raise pulumi.RunError(
            "WebappDatabaseStack requires at least one allowed_security_group_id."
        )
    if args.min_capacity < 0:
        raise pulumi.RunError("Aurora Serverless v2 min_capacity cannot be negative.")
    if args.max_capacity <= 0 or args.max_capacity > 256:
        raise pulumi.RunError(
            "Aurora Serverless v2 max_capacity must be within the AWS 0-256 ACU range."
        )
    if args.min_capacity > args.max_capacity:
        raise pulumi.RunError(
            "Aurora Serverless v2 min_capacity cannot exceed max_capacity."
        )
    if args.min_capacity == 0 and not _supports_zero_acu(args.engine_version):
        raise pulumi.RunError(_ZERO_ACU_GUIDANCE)
    if args.min_capacity == 0 and not (
        _MIN_SECONDS_UNTIL_AUTO_PAUSE
        <= args.seconds_until_auto_pause
        <= _MAX_SECONDS_UNTIL_AUTO_PAUSE
    ):
        raise pulumi.RunError(
            "Aurora Serverless v2 seconds_until_auto_pause must be between "
            f"{_MIN_SECONDS_UNTIL_AUTO_PAUSE} and {_MAX_SECONDS_UNTIL_AUTO_PAUSE}."
        )
    if args.backup_retention_days < 1:
        raise pulumi.RunError("backup_retention_days must be at least 1.")


def _aws_identifier(*parts: str, max_length: int = 63) -> str:
    raw = "-".join(part for part in parts if part)
    identifier = _IDENTIFIER_CLEANUP_RE.sub("-", raw.lower()).strip("-")
    if not identifier or not identifier[0].isalpha():
        identifier = f"db-{identifier}"
    return identifier[:max_length].rstrip("-")


def _master_user_secret_arn(secrets: Any) -> str:
    if not secrets:
        return ""
    first = secrets[0]
    if isinstance(first, dict):
        return first.get("secret_arn") or first.get("secretArn") or ""
    return getattr(first, "secret_arn", "")


def _deduplicated_security_group_ids(values: Sequence[Any]) -> list[Any]:
    """Return stable, unique peer ids without resolving Pulumi inputs."""
    strings = sorted(
        {value.strip() for value in values if isinstance(value, str) and value.strip()}
    )
    opaque: list[Any] = []
    for value in values:
        if not isinstance(value, str) and all(value is not peer for peer in opaque):
            opaque.append(value)
    return [*opaque, *strings]


def _database_ingress_rules(security_group_ids: Sequence[Any]) -> list[Any]:
    """Declare one inline ingress permission per approved peer group."""
    return [
        aws.ec2.SecurityGroupIngressArgs(
            description=_DATABASE_INGRESS_DESCRIPTION,
            protocol="tcp",
            from_port=_POSTGRES_PORT,
            to_port=_POSTGRES_PORT,
            security_groups=[security_group_id],
        )
        for security_group_id in _deduplicated_security_group_ids(security_group_ids)
    ]


class _MasterSecretRotationDisabledProvider(dynamic.ResourceProvider):
    """Pulumi dynamic provider that keeps RDS-managed master secret rotation off."""

    def _client(self) -> Any:
        import boto3

        return boto3.client("secretsmanager")

    def _disable_rotation(self, secret_arn: str) -> None:
        if not secret_arn:
            return
        client = self._client()
        secret = client.describe_secret(SecretId=secret_arn)
        if secret.get("RotationEnabled"):
            client.cancel_rotate_secret(SecretId=secret_arn)

    def create(self, props: dict[str, Any]) -> dynamic.CreateResult:
        secret_arn = props["secret_arn"]
        self._disable_rotation(secret_arn)
        return dynamic.CreateResult(
            id_=secret_arn,
            outs={**props, "rotation_enabled": False},
        )

    def diff(
        self,
        id_: str,
        olds: dict[str, Any],
        news: dict[str, Any],
    ) -> dynamic.DiffResult:
        return dynamic.DiffResult(
            changes=olds.get("secret_arn") != news.get("secret_arn"),
        )

    def update(
        self,
        id_: str,
        olds: dict[str, Any],
        news: dict[str, Any],
    ) -> dynamic.UpdateResult:
        secret_arn = news["secret_arn"]
        self._disable_rotation(secret_arn)
        return dynamic.UpdateResult(outs={**news, "rotation_enabled": False})

    def delete(self, id_: str, props: dict[str, Any]) -> None:
        # Deleting this Pulumi helper must not re-enable rotation on the secret.
        return None


class MasterSecretRotationDisabled(dynamic.Resource):
    """Declarative assertion that the RDS-managed master secret does not rotate."""

    rotation_enabled: pulumi.Output[bool]

    def __init__(
        self,
        name: str,
        secret_arn: pulumi.Input[str],
        opts: Optional[pulumi.ResourceOptions] = None,
    ) -> None:
        super().__init__(
            _MasterSecretRotationDisabledProvider(),
            name,
            {"secret_arn": secret_arn, "rotation_enabled": False},
            opts,
        )


class WebappDatabaseStack(pulumi.ComponentResource):
    """Aurora PostgreSQL Serverless v2 cluster with caller-owned networking."""

    security_group: aws.ec2.SecurityGroup
    subnet_group: aws.rds.SubnetGroup
    cluster: aws.rds.Cluster
    writer_instance: aws.rds.ClusterInstance
    master_secret_arn: pulumi.Output[str]
    master_secret_rotation_disabled: MasterSecretRotationDisabled

    def __init__(
        self,
        name: str,
        args: WebappDatabaseArgs,
        opts: Optional[pulumi.ResourceOptions] = None,
    ) -> None:
        super().__init__("webapp:infra:WebappDatabaseStack", name, None, opts)

        _validate_args(args)

        tags = {
            "project": args.deploy_namespace,
            "environment": args.environment,
        }
        child_opts = pulumi.ResourceOptions(parent=self)
        cluster_identifier = _aws_identifier(
            args.deploy_namespace, args.environment, "aurora"
        )
        subnet_group_name = _aws_identifier(
            args.deploy_namespace,
            args.environment,
            "aurora-subnets",
        )
        is_prod = args.environment == "prod"
        final_snapshot_identifier = None
        if is_prod:
            final_snapshot_identifier = _aws_identifier(
                args.deploy_namespace,
                args.environment,
                "aurora-final",
                max_length=255,
            )
        scaling_configuration = {
            "min_capacity": args.min_capacity,
            "max_capacity": args.max_capacity,
        }
        if args.min_capacity == 0:
            scaling_configuration["seconds_until_auto_pause"] = (
                args.seconds_until_auto_pause
            )

        self.security_group = aws.ec2.SecurityGroup(
            "databaseSecurityGroup",
            vpc_id=args.vpc_id,
            description=f"{args.deploy_namespace} {args.environment} Aurora PostgreSQL",
            ingress=_database_ingress_rules(args.allowed_security_group_ids),
            egress=[
                aws.ec2.SecurityGroupEgressArgs(
                    description="Allow database egress for AWS-managed maintenance",
                    protocol="-1",
                    from_port=0,
                    to_port=0,
                    cidr_blocks=["0.0.0.0/0"],
                ),
            ],
            tags=tags,
            opts=child_opts,
        )

        self.subnet_group = aws.rds.SubnetGroup(
            "databaseSubnetGroup",
            name=subnet_group_name,
            subnet_ids=args.subnet_ids,
            tags=tags,
            opts=child_opts,
        )

        self.cluster = aws.rds.Cluster(
            "databaseCluster",
            cluster_identifier=cluster_identifier,
            engine=aws.rds.EngineType.AURORA_POSTGRESQL,
            engine_mode=aws.rds.EngineMode.PROVISIONED,
            engine_version=args.engine_version,
            database_name=args.database_name,
            master_username=args.master_username,
            manage_master_user_password=True,
            db_subnet_group_name=self.subnet_group.name,
            vpc_security_group_ids=[self.security_group.id],
            backup_retention_period=args.backup_retention_days,
            copy_tags_to_snapshot=True,
            deletion_protection=is_prod,
            skip_final_snapshot=not is_prod,
            final_snapshot_identifier=final_snapshot_identifier,
            storage_encrypted=True,
            serverlessv2_scaling_configuration=scaling_configuration,
            tags=tags,
            opts=child_opts,
        )

        self.writer_instance = aws.rds.ClusterInstance(
            "databaseWriter",
            cluster_identifier=self.cluster.id,
            instance_class="db.serverless",
            engine=self.cluster.engine,
            engine_version=self.cluster.engine_version,
            publicly_accessible=False,
            db_subnet_group_name=self.subnet_group.name,
            tags=tags,
            opts=child_opts,
        )

        self.master_secret_arn = self.cluster.master_user_secrets.apply(
            _master_user_secret_arn
        )
        self.master_secret_rotation_disabled = MasterSecretRotationDisabled(
            "databaseMasterSecretRotationDisabled",
            self.master_secret_arn,
            opts=child_opts,
        )
        outputs = {
            "databaseClusterArn": self.cluster.arn,
            "databaseClusterEndpoint": self.cluster.endpoint,
            "databaseName": args.database_name,
            "databaseEngineVersion": self.cluster.engine_version,
            "databaseSecretArn": self.master_secret_arn,
            "databaseSecretRotationEnabled": (
                self.master_secret_rotation_disabled.rotation_enabled
            ),
            "databaseSecurityGroupId": self.security_group.id,
        }

        for key, value in outputs.items():
            pulumi.export(key, value)
        self.register_outputs(outputs)
