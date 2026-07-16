# AUTO-GENERATED template source: templates/webapp/infra/__main__.py. Do not hand-edit rendered copies; refresh through Yoke template/onboarding surfaces.
"""Pulumi entrypoint dispatched by stack name.

Each call to `pulumi up` against a project stack selects exactly one of the
ComponentResources defined alongside this file. Suffix-dispatched stacks pick
by stack-name suffix (`-infra`, `-vps`, `-domain`, `-registry`, or
`-runner-fleet`); environment stacks dispatch with `stack_kind=environment` in
the rendered stack config. A project instantiates only the stacks declared in
DB-backed project renderer settings.
"""

import json
import os
import sys

# pulumi-language-python on Python 3.14 does not implicitly add the
# Pulumi project directory to ``sys.path`` when launching ``__main__.py``,
# so branch-local sibling-module imports below would fail with ``ModuleNotFoundError``.
# Insert the script's own directory before the stdlib import statements.
_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_DIR)

import pulumi  # noqa: E402 -- sibling path must be installed before this import


def _infra_args_from_config(deploy_namespace: str):
    from webapp_infra_stack import WebappInfraArgs

    config = pulumi.Config()
    return WebappInfraArgs(
        domain_name=config.require("domain_name"),
        origin_host=config.require("origin_host"),
        deploy_namespace=deploy_namespace,
        hosted_zone_id=config.require("hosted_zone_id"),
        certificate_arn=config.get("certificate_arn") or "",
        origin_id=config.require("origin_id"),
        distribution_bucket_name=config.get("distribution_bucket_name") or "",
        distribution_origin_id=config.get("distribution_origin_id") or "",
        domain_txt_records=_domain_txt_records_from_config(config),
        domain_mx_records=_domain_mx_records_from_config(config),
    )


def _vps_args_from_config(deploy_namespace: str):
    from webapp_vps_stack import WebappVpsArgs

    config = pulumi.Config()
    return WebappVpsArgs(
        deploy_namespace=deploy_namespace,
        instance_type=config.require("vps_instance_type"),
        root_volume_gb=config.require_int("vps_root_volume_gb"),
        ssh_key_name=config.require("vps_ssh_key_name"),
        stack_name=pulumi.get_stack(),
        iam_instance_profile_name=(
            config.get("vps_iam_instance_profile_name") or None
        ),
    )


def _domain_args_from_config(deploy_namespace: str):
    from webapp_domain_stack import WebappDomainArgs

    config = pulumi.Config()
    return WebappDomainArgs(
        domain_name=config.require("domain_name"),
        deploy_namespace=deploy_namespace,
        # Optional: adopt an existing zone (e.g. one Route 53 auto-created on
        # domain registration) instead of creating a duplicate. Empty = create.
        import_zone_id=config.get("import_zone_id") or "",
        # Optional: defaults to False so the zone is set up before the
        # operator completes the console domain-registration purchase.
        manage_registration=config.get_bool("manage_registration") or False,
        domain_txt_records=_domain_txt_records_from_config(config),
        domain_mx_records=_domain_mx_records_from_config(config),
    )


def _domain_txt_records_from_config(config):
    from webapp_dns_records import DomainTxtRecordArgs

    raw = config.get("domain_txt_records") or "[]"
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise pulumi.RunError(
            f"domain_txt_records must be a JSON array: {exc}"
        ) from exc
    if not isinstance(loaded, list):
        raise pulumi.RunError("domain_txt_records must be a JSON array")

    parsed = []
    for index, item in enumerate(loaded):
        if not isinstance(item, dict):
            raise pulumi.RunError(f"domain_txt_records[{index}] must be an object")
        raw_values = item.get("values", item.get("records"))
        if raw_values is None and item.get("value") is not None:
            raw_values = [item.get("value")]
        if not isinstance(raw_values, list):
            raise pulumi.RunError(
                f"domain_txt_records[{index}] must declare value or values"
            )
        values = tuple(str(value) for value in raw_values if str(value))
        if not values:
            raise pulumi.RunError(
                f"domain_txt_records[{index}] must declare at least one value"
            )
        try:
            ttl = int(item.get("ttl") or 300)
        except (TypeError, ValueError) as exc:
            raise pulumi.RunError(
                f"domain_txt_records[{index}].ttl must be an integer"
            ) from exc
        parsed.append(
            DomainTxtRecordArgs(
                name=str(item.get("name") or "@"),
                values=values,
                ttl=ttl,
                resource_name=str(item.get("resource_name") or item.get("id") or ""),
            )
        )
    return tuple(parsed)


def _domain_mx_records_from_config(config):
    from webapp_dns_records import DomainMxRecordArgs

    raw = config.get("domain_mx_records") or "[]"
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise pulumi.RunError(f"domain_mx_records must be a JSON array: {exc}") from exc
    if not isinstance(loaded, list):
        raise pulumi.RunError("domain_mx_records must be a JSON array")

    parsed = []
    for index, item in enumerate(loaded):
        if not isinstance(item, dict):
            raise pulumi.RunError(f"domain_mx_records[{index}] must be an object")
        raw_values = item.get("values", item.get("records"))
        if raw_values is None and item.get("value") is not None:
            try:
                priority = int(item.get("priority"))
            except (TypeError, ValueError) as exc:
                raise pulumi.RunError(
                    f"domain_mx_records[{index}].priority must be an integer"
                ) from exc
            raw_values = [f"{priority} {str(item.get('value')).strip()}"]
        if not isinstance(raw_values, list):
            raise pulumi.RunError(
                f"domain_mx_records[{index}] must declare value or values"
            )
        values = tuple(str(value).strip() for value in raw_values if str(value).strip())
        if not values:
            raise pulumi.RunError(
                f"domain_mx_records[{index}] must declare at least one value"
            )
        try:
            ttl = int(item.get("ttl") or 300)
        except (TypeError, ValueError) as exc:
            raise pulumi.RunError(
                f"domain_mx_records[{index}].ttl must be an integer"
            ) from exc
        parsed.append(
            DomainMxRecordArgs(
                name=str(item.get("name") or "@"),
                values=values,
                ttl=ttl,
                resource_name=str(item.get("resource_name") or item.get("id") or ""),
            )
        )
    return tuple(parsed)


def _config_string_list(config, name: str) -> list[str]:
    values = config.get_object(name) or []
    if not isinstance(values, list) or any(
        not isinstance(value, str) or not value.strip() for value in values
    ):
        raise pulumi.RunError(f"{name} must be a JSON string array")
    return [value.strip() for value in values]


def _config_string_map(config, name: str) -> dict[str, str]:
    values = config.get_object(name) or {}
    if not isinstance(values, dict) or any(
        not isinstance(key, str) or not key.strip()
        or not isinstance(value, str) or not value.strip()
        for key, value in values.items()
    ):
        raise pulumi.RunError(f"{name} must be a JSON string map")
    return {key.strip(): value.strip() for key, value in values.items()}


def _registry_args_from_config(deploy_namespace: str):
    from webapp_registry_stack import WebappRegistryArgs

    config = pulumi.Config()
    manage_provider = config.get_bool("manage_github_oidc_provider")
    return WebappRegistryArgs(
        deploy_namespace=deploy_namespace,
        # Optional: defaults to the project's core repository name so a bare
        # registry stack config needs no extra key.
        repository_name=config.get("repository_name") or f"{deploy_namespace}-core",
        # Optional: empty renders the registry without GitHub CI federation.
        github_repo=config.get("github_repo") or "",
        github_api_url=config.get("github_api_url") or "https://api.github.com",
        # Optional: exactly one project per AWS account creates the
        # account-singleton GitHub OIDC provider; the rest reference it.
        manage_github_oidc_provider=(
            True if manage_provider is None else manage_provider
        ),
        aws_account_id=config.get("aws_account_id") or "",
        state_bucket=config.get("state_bucket") or "",
        kms_key_alias=config.get("kms_key_alias") or "",
        distribution_bucket_names=_config_string_list(
            config, "distribution_bucket_names"
        ),
        github_app_private_key_secret_arns=_config_string_list(
            config, "github_app_private_key_secret_arns"
        ),
    )


def _runner_fleet_args_from_config(deploy_namespace: str):
    from webapp_runner_fleet_config import WebappRunnerFleetArgs

    config = pulumi.Config()
    aws_config = pulumi.Config("aws")
    labels = json.loads(config.require("runner_labels"))
    return WebappRunnerFleetArgs(
        project=config.require("project_name"),
        deploy_namespace=deploy_namespace,
        aws_capability=config.require("aws_capability"),
        aws_region=aws_config.require("region"),
        github_capability=config.require("github_capability"),
        github_repo=config.require("github_repo"),
        github_repo_owner=config.require("github_repo_owner"),
        github_repo_name=config.require("github_repo_name"),
        github_installation_id=config.require("github_installation_id"),
        github_repository_id=config.require("github_repository_id"),
        github_app_issuer=config.require("github_app_issuer"),
        github_api_url=config.require("github_api_url"),
        github_web_url=config.require("github_web_url"),
        github_private_key_secret_arn=config.require("github_private_key_secret_arn"),
        token_broker_function=config.require("token_broker_function"),
        runner_labels=[str(label) for label in labels],
        runner_variable_name=config.require("runner_variable_name"),
        routing_enabled=config.require_bool("routing_enabled"),
        runner_count=config.require_int("runner_count"),
        max_runner_count=config.require_int("max_runner_count"),
        instance_type=config.require("instance_type"),
        architecture=config.require("architecture"),
        root_volume_gb=config.require_int("root_volume_gb"),
        idle_shutdown_minutes=config.require_int("idle_shutdown_minutes"),
        shutdown_mode=config.require("shutdown_mode"),
        deployment_ssh_stack_outputs=_config_string_map(
            config, "deployment_ssh_stack_outputs"
        ),
    )


def _environment_args_from_config(deploy_namespace: str, stack_name: str):
    from webapp_database_stack import DEFAULT_SECONDS_UNTIL_AUTO_PAUSE
    from webapp_environment_stack import WebappEnvironmentArgs

    config = pulumi.Config()
    seconds_until_auto_pause = config.get_int("database_seconds_until_auto_pause")
    return WebappEnvironmentArgs(
        deploy_namespace=deploy_namespace,
        environment=config.require("environment"),
        stack_name=stack_name,
        domain_name=config.require("domain_name"),
        api_host=config.require("api_host"),
        origin_host=config.require("origin_host"),
        hosted_zone_id=config.require("hosted_zone_id"),
        api_origin_port=config.require_int("api_origin_port"),
        distribution_bucket_name=config.get("distribution_bucket_name") or "",
        distribution_origin_id=config.get("distribution_origin_id") or "",
        distribution_base_url=config.get("distribution_base_url") or "",
        github_repo=config.get("github_repo") or "",
        github_api_url=config.get("github_api_url") or "https://api.github.com",
        vps_instance_type=config.require("vps_instance_type"),
        vps_root_volume_gb=config.require_int("vps_root_volume_gb"),
        vps_ssh_key_name=config.require("vps_ssh_key_name"),
        database_name=config.require("database_name"),
        database_master_username=config.require("database_master_username"),
        database_engine_version=config.require("database_engine_version"),
        database_min_capacity_acu=float(config.require("database_min_capacity_acu")),
        database_max_capacity_acu=float(config.require("database_max_capacity_acu")),
        database_backup_retention_days=config.require_int(
            "database_backup_retention_days",
        ),
        database_allowed_security_group_ids=_config_string_list(
            config, "database_allowed_security_group_ids"
        ),
        database_seconds_until_auto_pause=(
            DEFAULT_SECONDS_UNTIL_AUTO_PAUSE
            if seconds_until_auto_pause is None
            else seconds_until_auto_pause
        ),
        container_repository_name=config.get("container_repository_name") or "",
        ephemeral_preview_domain=config.get("ephemeral_preview_domain") or "",
        github_app_private_key_secret_arn=(
            config.get("github_app_private_key_secret_arn") or ""
        ),
        github_app_kms_key_arn=config.get("github_app_kms_key_arn") or "",
    )


def main() -> None:
    stack = pulumi.get_stack()
    config = pulumi.Config()
    deploy_namespace = config.require("deploy_namespace")
    stack_kind = config.get("stack_kind") or ""

    if stack_kind == "environment":
        from webapp_environment_stack import WebappEnvironmentStack

        WebappEnvironmentStack(
            stack, _environment_args_from_config(deploy_namespace, stack)
        )
    elif stack.endswith("-infra"):
        from webapp_infra_stack import WebappInfraStack

        WebappInfraStack(stack, _infra_args_from_config(deploy_namespace))
    elif stack.endswith("-vps"):
        from webapp_vps_stack import WebappVpsStack

        WebappVpsStack(stack, _vps_args_from_config(deploy_namespace))
    elif stack.endswith("-domain"):
        from webapp_domain_stack import WebappDomainStack

        WebappDomainStack(stack, _domain_args_from_config(deploy_namespace))
    elif stack.endswith("-registry"):
        from webapp_registry_stack import WebappRegistryStack

        WebappRegistryStack(stack, _registry_args_from_config(deploy_namespace))
    elif stack.endswith("-runner-fleet"):
        from webapp_runner_fleet_stack import WebappRunnerFleetStack

        WebappRunnerFleetStack(
            stack,
            _runner_fleet_args_from_config(deploy_namespace),
        )
    else:
        raise pulumi.RunError(
            f"Unknown Pulumi stack '{stack}'. Expected a name ending in "
            "'-infra', '-vps', '-domain', '-registry', or '-runner-fleet', or "
            "stack_kind=environment (e.g. '<project>-infra', "
            "'<project>-vps', '<project>-domain', '<project>-registry', "
            "'<project>-runner-fleet', or '<project>-prod')."
        )


main()
