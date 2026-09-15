"""Fixtures shared by the tests in this directory.

``deploy_seams`` lives here rather than in a helper module because pytest
resolves fixtures by name from a conftest; importing one into each test
module instead shadows the parameter it is requested by.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import deploy_ephemeral
from runtime.api.domain.deploy_ephemeral_test_support import (
    Tracker,
    env,
    policy,
)


@pytest.fixture
def deploy_seams(monkeypatch):
    """Mock every non-runner seam so command plans drive the assertions."""
    tracker = Tracker()
    monkeypatch.setattr(deploy_ephemeral, "load_ephemeral_policy", lambda p: policy())
    monkeypatch.setattr(
        deploy_ephemeral,
        "resolve_deploy_environment",
        lambda p, e: env(),
    )
    monkeypatch.setattr(
        deploy_ephemeral, "aws_capability_env", lambda p, r: {"AWS": "1"}
    )
    monkeypatch.setattr(
        deploy_ephemeral,
        "ensure_instance_running",
        lambda runner, env, aws_env, emit: None,
    )
    monkeypatch.setattr(
        deploy_ephemeral,
        "wait_ssh_reachable",
        lambda runner, env, emit: None,
    )
    monkeypatch.setattr(
        deploy_ephemeral,
        "ensure_image_in_registry",
        lambda runner, env, aws_env, repo_path, tag, emit: f"reg/yoke-core:{tag}",
    )
    monkeypatch.setattr(
        deploy_ephemeral,
        "wait_container_healthy",
        lambda runner, env, name, emit: None,
    )
    monkeypatch.setattr(
        deploy_ephemeral,
        "render_webapp_template",
        lambda _root, relative, values: f"rendered:{relative}",
    )
    monkeypatch.setattr(deploy_ephemeral, "track", tracker)
    monkeypatch.setattr(deploy_ephemeral, "emit_ephemeral_event", lambda *a, **k: None)
    return tracker
