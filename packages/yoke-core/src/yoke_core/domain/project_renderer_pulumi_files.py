"""Program-file inventories for rendered Pulumi stack families."""

SHARED_PROGRAM_FILES = (
    "__main__.py",
    "requirements.txt",
    "webapp_component_aliases.py",
    "webapp_github_repository_provider.py",
    "webapp_stack_config.py",
)
ENVIRONMENT_PROGRAM_FILES = (
    "webapp_database_stack.py",
    "webapp_api_stack.py",
    "webapp_distribution_stack.py",
    "webapp_distribution_github_variables.py",
    "webapp_environment_stack.py",
    "webapp_environment_origin_policy.py",
)
REGISTRY_PROGRAM_FILES = (
    "webapp_registry_ci_metadata_policy.py",
    "webapp_registry_ci_policy.py",
    "webapp_registry_github_variables.py",
)
RUNNER_FLEET_PROGRAM_FILES = (
    "webapp_runner_authority_intent.py",
    "webapp_runner_fleet_config.py",
    "webapp_runner_host_cycle.py",
    "webapp_runner_fleet_internals.py",
    "webapp_runner_fleet_iam.py",
    "webapp_runner_fleet_network.py",
    "webapp_runner_github_broker_stack.py",
    "webapp_runner_github_state.py",
    "webapp_runner_github_webhook.py",
    "webapp_runner_aws_state.mjs",
    "webapp_runner_github_api.mjs",
    "webapp_runner_github_broker.mjs",
    "webapp_runner_parallel_reaper.mjs",
    "webapp_runner_registration.mjs",
    "webapp_runner_termination.mjs",
)


__all__ = [
    "ENVIRONMENT_PROGRAM_FILES",
    "REGISTRY_PROGRAM_FILES",
    "RUNNER_FLEET_PROGRAM_FILES",
    "SHARED_PROGRAM_FILES",
]
