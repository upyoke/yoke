# AUTO-GENERATED template source: templates/webapp/infra/webapp_runner_fleet_stack.py. Do not hand-edit rendered copies; refresh through Yoke template/onboarding surfaces.
"""Pulumi ComponentResource for a disposable GitHub Actions runner fleet."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, Sequence

import pulumi
from pulumi import dynamic
import pulumi_aws as aws

from webapp_runner_fleet_internals import (
    _ami_arch,
    _assume_role_policy,
    _inline_policy,
    _user_data,
    _webhook_lambda_code,
)


@dataclass
class WebappRunnerFleetArgs:
    """Inputs for ``WebappRunnerFleetStack``."""

    deploy_namespace: str
    github_repo: str
    runner_labels: Sequence[str]
    runner_count: int
    max_runner_count: int
    instance_type: str
    architecture: str
    root_volume_gb: int
    idle_shutdown_minutes: int
    shutdown_mode: str


# The Function-URL provider and the helpers it references stay in this module on
# purpose: Pulumi serializes the dynamic provider into state by its defining
# module path, so relocating it would rewrite ``__provider`` and force a no-op
# resource update on every deploy.
def _lambda_error_code(exc: Exception) -> str:
    response = getattr(exc, "response", {}) or {}
    error = response.get("Error", {}) if isinstance(response, dict) else {}
    code = error.get("Code", "") if isinstance(error, dict) else ""
    return str(code)


def _add_url_invoke_permission(props: dict) -> None:
    import boto3

    client = boto3.client("lambda", region_name=str(props["region"]))
    try:
        client.add_permission(
            FunctionName=str(props["function_name"]),
            StatementId=str(props["statement_id"]),
            Action="lambda:InvokeFunction",
            Principal="*",
            InvokedViaFunctionUrl=True,
        )
    except Exception as exc:
        if _lambda_error_code(exc) != "ResourceConflictException":
            raise


def _remove_url_invoke_permission(props: dict) -> None:
    import boto3

    client = boto3.client("lambda", region_name=str(props["region"]))
    try:
        client.remove_permission(
            FunctionName=str(props["function_name"]),
            StatementId=str(props["statement_id"]),
        )
    except Exception as exc:
        if _lambda_error_code(exc) != "ResourceNotFoundException":
            raise


class _FunctionUrlInvokePermissionProvider(dynamic.ResourceProvider):
    def create(self, props: dict) -> dynamic.CreateResult:
        _add_url_invoke_permission(props)
        resource_id = f"{props['function_name']}:{props['statement_id']}"
        return dynamic.CreateResult(id_=resource_id, outs=props)

    def delete(self, id_: str, props: dict) -> None:
        _remove_url_invoke_permission(props)


class _FunctionUrlInvokePermission(dynamic.Resource):
    def __init__(
        self,
        name: str,
        *,
        function_name: pulumi.Input[str],
        region: str,
        opts: Optional[pulumi.ResourceOptions] = None,
    ) -> None:
        super().__init__(
            _FunctionUrlInvokePermissionProvider(),
            name,
            {
                "function_name": function_name,
                "region": region,
                "statement_id": "FunctionURLAllowPublicInvokeOnly",
            },
            opts,
        )


class WebappRunnerFleetStack(pulumi.ComponentResource):
    """Scale-to-zero self-hosted GitHub Actions runner fleet."""

    def __init__(
        self,
        name: str,
        args: WebappRunnerFleetArgs,
        opts: Optional[pulumi.ResourceOptions] = None,
    ) -> None:
        super().__init__("webapp:infra:WebappRunnerFleetStack", name, None, opts)
        if args.shutdown_mode != "terminate":
            raise ValueError("runner fleet v1 supports shutdown_mode=terminate")

        region = aws.get_region().name
        tags = {"project": args.deploy_namespace, "component": "github-actions"}
        child_opts = pulumi.ResourceOptions(parent=self)
        prefix = f"/{args.deploy_namespace}/github-actions-runner-fleet"
        asg_name = f"{args.deploy_namespace}-github-actions-runner-fleet"
        github_token_parameter_name = f"{prefix}/github-token"
        webhook_secret_parameter_name = f"{prefix}/webhook-secret"

        self.github_token_parameter = aws.ssm.Parameter(
            "runnerFleetGithubToken",
            name=github_token_parameter_name,
            type="SecureString",
            value="pending-runner-fleet-secret-bootstrap",
            tags=tags,
            opts=pulumi.ResourceOptions.merge(
                child_opts,
                pulumi.ResourceOptions(ignore_changes=["value"]),
            ),
        )
        self.webhook_secret_parameter = aws.ssm.Parameter(
            "runnerFleetWebhookSecret",
            name=webhook_secret_parameter_name,
            type="SecureString",
            value="pending-runner-fleet-secret-bootstrap",
            tags=tags,
            opts=pulumi.ResourceOptions.merge(
                child_opts,
                pulumi.ResourceOptions(ignore_changes=["value"]),
            ),
        )

        default_vpc = aws.ec2.get_vpc(default=True)
        subnets = aws.ec2.get_subnets(filters=[
            aws.ec2.GetSubnetsFilterArgs(name="vpc-id", values=[default_vpc.id]),
        ])
        self.security_group = aws.ec2.SecurityGroup(
            "runnerFleetSecurityGroup",
            vpc_id=default_vpc.id,
            description="Yoke GitHub Actions runners - outbound only",
            ingress=[],
            egress=[aws.ec2.SecurityGroupEgressArgs(
                description="Allow all outbound traffic",
                protocol="-1",
                from_port=0,
                to_port=0,
                cidr_blocks=["0.0.0.0/0"],
            )],
            tags=tags,
            opts=child_opts,
        )

        self.instance_role = aws.iam.Role(
            "runnerFleetInstanceRole",
            assume_role_policy=_assume_role_policy("ec2.amazonaws.com"),
            tags=tags,
            opts=child_opts,
        )
        aws.iam.RolePolicyAttachment(
            "runnerFleetSsmManagedInstanceCore",
            role=self.instance_role.name,
            policy_arn=(
                "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
            ),
            opts=child_opts,
        )
        aws.iam.RolePolicy(
            "runnerFleetInstancePolicy",
            role=self.instance_role.id,
            policy=_inline_policy([
                "ssm:GetParameter",
                "autoscaling:DescribeAutoScalingGroups",
                "autoscaling:SetDesiredCapacity",
            ]),
            opts=child_opts,
        )
        self.instance_profile = aws.iam.InstanceProfile(
            "runnerFleetInstanceProfile",
            role=self.instance_role.name,
            tags=tags,
            opts=child_opts,
        )

        ami_param = aws.ssm.get_parameter(
            name=(
                "/aws/service/canonical/ubuntu/server/24.04/stable/current/"
                f"{_ami_arch(args.architecture)}/hvm/ebs-gp3/ami-id"
            ),
        )
        self.launch_template = aws.ec2.LaunchTemplate(
            "runnerFleetLaunchTemplate",
            image_id=ami_param.value,
            instance_type=args.instance_type,
            # New template versions become the default automatically, so the ASG's
            # $Latest and the default version never diverge — prevents a stale
            # (e.g. pre-rename) default version bootstrapping a broken runner.
            update_default_version=True,
            iam_instance_profile=aws.ec2.LaunchTemplateIamInstanceProfileArgs(
                name=self.instance_profile.name,
            ),
            vpc_security_group_ids=[self.security_group.id],
            user_data=_user_data(
                args=args,
                region=region,
                asg_name=asg_name,
                github_token_parameter=github_token_parameter_name,
            ),
            block_device_mappings=[
                aws.ec2.LaunchTemplateBlockDeviceMappingArgs(
                    device_name="/dev/sda1",
                    ebs=aws.ec2.LaunchTemplateBlockDeviceMappingEbsArgs(
                        volume_size=args.root_volume_gb,
                        volume_type="gp3",
                        encrypted=True,
                        delete_on_termination=True,
                    ),
                ),
            ],
            tag_specifications=[
                aws.ec2.LaunchTemplateTagSpecificationArgs(
                    resource_type="instance",
                    tags={**tags, "Name": asg_name},
                ),
                aws.ec2.LaunchTemplateTagSpecificationArgs(
                    resource_type="volume",
                    tags=tags,
                ),
            ],
            tags=tags,
            opts=child_opts,
        )
        self.asg = aws.autoscaling.Group(
            "runnerFleetAsg",
            name=asg_name,
            min_size=0,
            max_size=1,
            vpc_zone_identifiers=subnets.ids,
            launch_template=aws.autoscaling.GroupLaunchTemplateArgs(
                id=self.launch_template.id,
                version="$Latest",
            ),
            tags=[
                aws.autoscaling.GroupTagArgs(
                    key=key, value=value, propagate_at_launch=True,
                )
                for key, value in tags.items()
            ],
            opts=pulumi.ResourceOptions.merge(
                child_opts,
                pulumi.ResourceOptions(ignore_changes=["desiredCapacity"]),
            ),
        )

        self.webhook_role = aws.iam.Role(
            "runnerFleetWebhookRole",
            assume_role_policy=_assume_role_policy("lambda.amazonaws.com"),
            tags=tags,
            opts=child_opts,
        )
        aws.iam.RolePolicyAttachment(
            "runnerFleetWebhookLogs",
            role=self.webhook_role.name,
            policy_arn=(
                "arn:aws:iam::aws:policy/service-role/"
                "AWSLambdaBasicExecutionRole"
            ),
            opts=child_opts,
        )
        aws.iam.RolePolicy(
            "runnerFleetWebhookPolicy",
            role=self.webhook_role.id,
            policy=_inline_policy([
                "ssm:GetParameter",
                "autoscaling:SetDesiredCapacity",
            ]),
            opts=child_opts,
        )
        self.webhook_function = aws.lambda_.Function(
            "runnerFleetWebhook",
            role=self.webhook_role.arn,
            runtime="python3.12",
            handler="index.handler",
            timeout=10,
            code=pulumi.AssetArchive({
                "index.py": pulumi.StringAsset(_webhook_lambda_code()),
            }),
            environment=aws.lambda_.FunctionEnvironmentArgs(
                variables={
                    "ASG_NAME": asg_name,
                    "WEBHOOK_SECRET_PARAMETER": webhook_secret_parameter_name,
                    "REQUIRED_LABELS": ",".join(args.runner_labels),
                },
            ),
            tags=tags,
            opts=child_opts,
        )
        self.webhook_url = aws.lambda_.FunctionUrl(
            "runnerFleetWebhookUrl",
            function_name=self.webhook_function.name,
            authorization_type="NONE",
            opts=child_opts,
        )
        url_permission = aws.lambda_.Permission(
            "runnerFleetWebhookUrlPermission", action="lambda:InvokeFunctionUrl",
            function=self.webhook_function.name, principal="*",
            function_url_auth_type="NONE", opts=child_opts,
        )
        _FunctionUrlInvokePermission(
            "runnerFleetWebhookUrlInvokePermission",
            function_name=self.webhook_function.name,
            region=region,
            opts=pulumi.ResourceOptions.merge(
                child_opts,
                pulumi.ResourceOptions(depends_on=[
                    self.webhook_url, url_permission,
                ]),
            ),
        )

        # Manage the GitHub repo webhook that drives ASG scaling as IaC, so a
        # fleet repoint (github_repo change + apply) moves the subscription
        # automatically instead of an out-of-band hand edit. Opt-in via a
        # dedicated RUNNER_FLEET_WEBHOOK_TOKEN (a token with `Webhooks: write`):
        # when absent the fleet keeps its prior out-of-band webhook (backward
        # compatible, and the automatic CI GITHUB_TOKEN never triggers this
        # path). The signing secret is read from the same SSM parameter the
        # scaling Lambda validates against, so GitHub's delivery signature and
        # the Lambda's check can never diverge.
        github_token = os.environ.get("RUNNER_FLEET_WEBHOOK_TOKEN")
        if github_token and "/" in args.github_repo:
            import pulumi_github as github

            gh_owner, _, gh_repo = args.github_repo.partition("/")
            github_provider = github.Provider(
                "runnerFleetGithubProvider",
                owner=gh_owner,
                token=github_token,
                opts=child_opts,
            )
            webhook_secret_value = aws.ssm.get_parameter(
                name=webhook_secret_parameter_name,
                with_decryption=True,
            ).value
            self.github_webhook = github.RepositoryWebhook(
                "runnerFleetGithubWebhook",
                repository=gh_repo,
                events=["workflow_job"],
                active=True,
                configuration={
                    "url": self.webhook_url.function_url,
                    "content_type": "json",
                    "insecure_ssl": False,
                    "secret": webhook_secret_value,
                },
                opts=pulumi.ResourceOptions.merge(
                    child_opts,
                    pulumi.ResourceOptions(provider=github_provider),
                ),
            )

        outputs = {
            "runnerFleetAsgName": self.asg.name,
            "runnerFleetWebhookUrl": self.webhook_url.function_url,
            "runnerFleetLabels": list(args.runner_labels),
        }
        for key, value in outputs.items():
            pulumi.export(key, value)
        self.register_outputs(outputs)
