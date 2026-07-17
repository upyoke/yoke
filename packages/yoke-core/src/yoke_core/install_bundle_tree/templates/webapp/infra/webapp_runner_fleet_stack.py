# AUTO-GENERATED template source: templates/webapp/infra/webapp_runner_fleet_stack.py. Do not hand-edit rendered copies; refresh through Yoke template/onboarding surfaces.
"""Pulumi ComponentResource for a disposable GitHub Actions runner fleet."""

from __future__ import annotations

from typing import Optional

import pulumi
from pulumi import dynamic
import pulumi_aws as aws
import pulumi_random as random

from webapp_runner_fleet_internals import (
    _ami_arch,
    _user_data,
    _webhook_lambda_code,
)
from webapp_runner_fleet_config import (
    WebappRunnerFleetArgs,
    validate_runner_fleet_configuration,
)
from webapp_runner_fleet_iam import (
    create_instance_identity,
    create_webhook_identity,
    grant_instance_runtime,
    grant_webhook_runtime,
)
from webapp_runner_fleet_network import create_runner_network
from webapp_runner_authority_intent import require_matching_authority_intent
from webapp_runner_github_broker_stack import create_runner_github_broker
import webapp_runner_github_webhook as runner_webhook

# Keep this provider's module path stable because Pulumi serializes it in state.
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
            {"function_name": function_name, "region": region,
             "statement_id": "FunctionURLAllowPublicInvokeOnly"},
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
        require_matching_authority_intent(
            args, stack_name=pulumi.get_stack(),
        )
        super().__init__("webapp:infra:WebappRunnerFleetStack", name, None, opts)
        validate_runner_fleet_configuration(args)
        runner_webhook.require_repository_token_environment()
        region = aws.get_region().name
        tags = {"project": args.deploy_namespace, "component": "github-actions"}
        child_opts = pulumi.ResourceOptions(parent=self)
        prefix = f"/{args.deploy_namespace}/github-actions-runner-fleet"
        asg_name = f"{args.deploy_namespace}-github-actions-runner-fleet"
        webhook_secret_parameter_name = f"{prefix}/webhook-secret"

        self.webhook_secret = random.RandomPassword(
            "runnerFleetWebhookSecretValue",
            length=64,
            special=False,
            opts=child_opts,
        )
        self.webhook_secret_parameter = aws.ssm.Parameter(
            "runnerFleetWebhookSecret",
            name=webhook_secret_parameter_name,
            type="SecureString",
            value=self.webhook_secret.result,
            tags=tags,
            opts=child_opts,
        )
        github_broker = create_runner_github_broker(
            args,
            region=region,
            asg_name=asg_name,
            parameter_prefix=prefix,
            tags=tags,
            child_opts=child_opts,
        )
        self.github_broker_function = github_broker.bootstrap_function
        self.queue_activity_parameter = github_broker.queue_activity_parameter
        self.runner_progress_parameter = github_broker.runner_progress_parameter
        self.runner_completion_parameter = github_broker.runner_completion_parameter

        network = create_runner_network(
            tags=tags,
            deployment_ssh_stack_outputs=args.deployment_ssh_stack_outputs,
            child_opts=child_opts,
        )
        self.vpc = network.vpc
        self.subnet = network.subnet
        self.security_group = network.security_group

        self.instance_role, self.instance_profile = create_instance_identity(
            tags=tags, child_opts=child_opts,
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
            # Make every new template version the ASG's default.
            update_default_version=True,
            iam_instance_profile=aws.ec2.LaunchTemplateIamInstanceProfileArgs(
                name=self.instance_profile.name,
            ),
            vpc_security_group_ids=[self.security_group.id],
            user_data=_user_data(
                args=args,
                region=region,
                github_broker_function=args.token_broker_function,
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
            vpc_zone_identifiers=[self.subnet.id],
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
        grant_instance_runtime(
            self.instance_role,
            broker_arn=self.github_broker_function.arn,
            child_opts=child_opts,
        )

        self.webhook_role = create_webhook_identity(
            tags=tags, child_opts=child_opts,
        )
        webhook_runtime = grant_webhook_runtime(
            self.webhook_role,
            parameter_arn=self.webhook_secret_parameter.arn,
            queue_activity_arn=self.queue_activity_parameter.arn,
            runner_progress_arn=self.runner_progress_parameter.arn,
            runner_completion_arn=self.runner_completion_parameter.arn,
            asg_arn=self.asg.arn,
            child_opts=child_opts,
        )
        self.webhook_function = aws.lambda_.Function(
            "runnerFleetWebhook",
            role=self.webhook_role.arn,
            runtime="python3.12",
            handler="index.handler",
            timeout=10,
            reserved_concurrent_executions=5,
            code=pulumi.AssetArchive({
                "index.py": pulumi.StringAsset(_webhook_lambda_code()),
            }),
            environment=aws.lambda_.FunctionEnvironmentArgs(
                variables={
                    "ASG_NAME": asg_name,
                    "WEBHOOK_SECRET_PARAMETER": webhook_secret_parameter_name,
                    "QUEUE_ACTIVITY_PARAMETER": (self.queue_activity_parameter.name),
                    "RUNNER_PROGRESS_PARAMETER": (self.runner_progress_parameter.name),
                    "RUNNER_COMPLETION_PARAMETER": (
                        self.runner_completion_parameter.name
                    ),
                    "EXPECTED_REPOSITORY_ID": args.github_repository_id,
                    "EXPECTED_REPOSITORY": args.github_repo,
                    "RUNNER_PREFIX": f"{args.deploy_namespace}-github-actions-",
                    # Forces fresh Lambda runtimes when SSM rotates the HMAC;
                    # the value is parameter metadata, never secret material.
                    "WEBHOOK_SECRET_VERSION": (
                        self.webhook_secret_parameter.version.apply(str)
                    ),
                    "REQUIRED_LABELS": ",".join(args.runner_labels),
                },
            ),
            tags=tags,
            opts=pulumi.ResourceOptions.merge(
                child_opts,
                pulumi.ResourceOptions(depends_on=[webhook_runtime]),
            ),
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
        url_invoke_permission = _FunctionUrlInvokePermission(
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

        (
            self.github_webhook,
            self.github_actions_variable,
        ) = runner_webhook.create_repository_automation(
            owner=args.github_repo_owner,
            repository=args.github_repo_name,
            api_url=args.github_api_url,
            webhook_url=self.webhook_url.function_url,
            webhook_secret=self.webhook_secret.result,
            variable_name=args.runner_variable_name,
            runner_labels=args.runner_labels,
            routing_enabled=args.routing_enabled,
            ingress_ready=[url_permission, url_invoke_permission],
            child_opts=child_opts,
        )

        outputs = {
            "runnerFleetAsgName": self.asg.name,
            "runnerFleetWebhookUrl": self.webhook_url.function_url,
            "runnerFleetWebhookSecretParameter": self.webhook_secret_parameter.name,
            "runnerFleetWebhookEvent": "workflow_job",
            "runnerFleetLabels": list(args.runner_labels),
            "runnerFleetRoutingEnabled": args.routing_enabled,
            "runnerFleetRoutingVariableName": args.runner_variable_name,
        }
        for key, value in outputs.items():
            pulumi.export(key, value)
        self.register_outputs(outputs)
