# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from unittest import mock as mock

import pytest

import yoke_core.engines.resync as resync_mod

from yoke_core.engines.resync import (
    DriftRecord as DriftRecord,
    PairedItem as PairedItem,
)

from yoke_core.domain.project_github_auth import ProjectGithubAuth

from runtime.api.engines._resync_test_helpers import (
    populated_db as populated_db,  # noqa: F401 — imported pytest fixture
    test_db,  # noqa: F401 — imported pytest fixture
)


def _fake_auth(token: str = "test-token", project: str = "yoke") -> ProjectGithubAuth:
    return ProjectGithubAuth(
        project=project,
        repo=f"org/{project}",
        token=token,
    )


@pytest.fixture(autouse=True)
def _auth_resolver():
    """Stub the canonical resolver so ``_call_domain_sync`` and
    ``_repair_local_orphan_backlog`` succeed in unit tests.

    Runtime and repair helpers resolve once before invoking domain sync helpers.
    """

    def resolver(project, **_):
        return _fake_auth(project=project or "yoke")

    with (
        mock.patch(
            "yoke_core.engines.resync_runtime.resolve_project_github_auth",
            side_effect=resolver,
        ),
        mock.patch(
            "yoke_core.engines.resync_repair.resolve_project_github_auth",
            side_effect=resolver,
        ),
    ):
        yield
