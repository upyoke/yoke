"""DB-backed Pulumi stack-state rendering for project-level stacks."""

from __future__ import annotations

from yoke_core.domain.project_renderer_pulumi_state import (
    _operator_state_lines_from_settings,
)
from yoke_core.domain.project_renderer_settings import ProjectRendererSettings
from runtime.api.domain.test_project_renderer_pulumi import _settings_from_context


def test_project_level_stack_state_renders_from_capability_without_site():
    base = _settings_from_context("platform", {"projectName": "platform"})
    capabilities = dict(base.capabilities)
    capabilities["pulumi-state"] = {
        "deploy_namespace": "yoke",
        "stacks": ["registry", "runner-fleet"],
        "stack_state": {
            "yoke-registry": {
                "secrets_provider": "awskms://alias/yoke-pulumi-state",
                "encrypted_key": "CAPABILITY_ENCRYPTED==",
            }
        },
    }
    settings = ProjectRendererSettings(
        project=base.project,
        deploy_namespace="yoke",
        display_name=base.display_name,
        site_id="",
        site_settings={},
        primary_environment=None,
        environments=(),
        capabilities=capabilities,
    )

    assert _operator_state_lines_from_settings(settings, "yoke-registry") == (
        "secretsprovider: awskms://alias/yoke-pulumi-state\n"
        "encryptedkey: CAPABILITY_ENCRYPTED==\n"
    )


def test_project_level_stack_state_ignores_other_stacks():
    settings = _settings_from_context("yoke", {"projectName": "yoke"})

    assert _operator_state_lines_from_settings(
        settings, "yoke-runner-fleet",
    ) == ""
