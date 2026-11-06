# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from unittest import mock

import pytest

from runtime.api.fixtures import pg_testdb

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

from yoke_core.domain.github_app_user_verification import (
    VerifiedProjectGitHubBinding,
)

from yoke_core.domain import project_github_binding as binding_domain

from yoke_core.domain.handlers.__init_register__ import register_all_handlers

from yoke_core.domain.handlers.project_github_binding import (
    handle_project_github_binding_bind,
)

from yoke_core.domain.project_github_binding import (
    cmd_bind_project_repo,
    cmd_project_github_binding_status,
    cmd_unbind_project_repo,
    normalize_github_repo,
)

from yoke_core.domain.yoke_function_dispatch import dispatch

from yoke_core.domain.yoke_function_permissions import DispatchPermission

from yoke_core.domain.yoke_function_registry import reset_registry_for_tests


def _verified(
    *,
    permissions=None,
    github_repo="Example-Org/ExternalWebapp",
    installation_status="active",
) -> VerifiedProjectGitHubBinding:
    return VerifiedProjectGitHubBinding(
        installation_id="12345",
        account_id="9988",
        account_login="Example-Org",
        account_type="Organization",
        repository_selection="selected",
        permissions=permissions
        or {
            "metadata": "read",
            "issues": "write",
            "pull_requests": "write",
            "contents": "write",
            "actions": "write",
            "checks": "read",
            "statuses": "read",
            "workflows": "write",
            "secrets": "write",
            "actions_variables": "write",
        },
        repository_id="4567",
        github_repo=github_repo,
        default_branch="trunk",
        repository_is_private=True,
        installation_status=installation_status,
    )
