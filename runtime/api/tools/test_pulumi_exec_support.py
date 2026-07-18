"""Shared Pulumi execution test settings."""

from yoke_core.domain.project_renderer_settings import ProjectRendererSettings


def _init_settings(
    *,
    stacks: list[str] | None = None,
    stack_state: dict | None = None,
) -> ProjectRendererSettings:
    state = {
        "stacks": stacks if stacks is not None else ["registry"],
        "state_bucket": "externalwebapp-pulumi-state",
        "kms_key_alias": "alias/externalwebapp-pulumi-state",
    }
    if stack_state is not None:
        state["stack_state"] = stack_state
    return ProjectRendererSettings(
        project="externalwebapp",
        deploy_namespace="externalwebapp",
        display_name="ExternalWebapp",
        site_id="",
        site_settings={},
        primary_environment=None,
        environments=(),
        capabilities={
            "aws-admin": {
                "account_id": "657517041453",
                "region": "us-east-1",
            },
            "github": {
                "repo_owner": "beebauman",
                "repo_name": "externalwebapp",
            },
            "pulumi-state": state,
        },
    )
