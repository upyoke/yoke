"""Program-file inventories for rendered Pulumi stack families."""

SHARED_PROGRAM_FILES = (
    "__main__.py",
    "requirements.txt",
)
ENVIRONMENT_PROGRAM_FILES = (
    "webapp_vps_stack.py",
    "webapp_database_stack.py",
    "webapp_api_stack.py",
    "webapp_distribution_stack.py",
    "webapp_environment_stack.py",
)
RUNNER_FLEET_PROGRAM_FILES = (
    "webapp_runner_fleet_internals.py",
    "webapp_runner_fleet_iam.py",
    "webapp_runner_fleet_network.py",
    "webapp_runner_github_broker_stack.py",
    "webapp_runner_github_state.py",
    "webapp_runner_aws_state.mjs",
    "webapp_runner_github_api.mjs",
    "webapp_runner_github_broker.mjs",
    "webapp_runner_termination.mjs",
)


__all__ = [
    "ENVIRONMENT_PROGRAM_FILES",
    "RUNNER_FLEET_PROGRAM_FILES",
    "SHARED_PROGRAM_FILES",
]
