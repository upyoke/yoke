"""Aurora mode for ``yoke dev db-admin setup``: the AWS managed cluster.

The environment's Postgres is an Aurora cluster found through its Pulumi
stack outputs, and the profile reads the DSN from the stack's AWS Secrets
Manager secret at run time. This mode is removed at the BYE-AWS Aurora purge;
until then both live environments use it.
"""

from __future__ import annotations

from typing import Any, Mapping

from yoke_cli.config.db_admin_setup_errors import DbAdminSetupError

AUTHORITY_KIND = "aws_aurora_postgres"


def plan(
    env: Any, project: str, env_name: str, admin_env: str, database_name: str
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Return the Aurora authority and the non-secret write plan steps."""
    authority = {
        "kind": AUTHORITY_KIND,
        "location": {
            "stack": env.stack_name,
            "region": env.aws_region,
            "database_name": database_name,
        },
    }
    steps = [
        {"action": "resolve-deploy-environment", "target": f"{project}/{env_name}"},
        {
            "action": "resolve-non-secret-cloud-database-binding",
            "target": env.stack_name,
        },
        {"action": "configure-managed-secret-authority", "target": admin_env},
    ]
    return authority, steps


def required_output(env: Any, outputs: Mapping[str, Any], name: str) -> str:
    """One non-empty Pulumi stack output, or a refusal naming the repair."""
    value = str(outputs.get(name) or "").strip()
    if not value:
        raise DbAdminSetupError(
            f"stack {env.stack_name} outputs are missing {name}; deploy the "
            f"{env.project}/{env.env_name} stack or correct the declared output name"
        )
    return value


__all__ = ["AUTHORITY_KIND", "plan", "required_output"]
