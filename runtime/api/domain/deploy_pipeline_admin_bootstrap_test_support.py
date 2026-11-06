# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from runtime.api.domain.deploy_pipeline_https_execution_test_support import (
    FLOW,
    LINEAGE,
    PROJECT,
    _install_test_https,
    _invoke,
    _replace_flow,
    serving_plane,
)

from yoke_cli.commands.adapters.deployment_execution_authority import (
    execution_connection_error,
)

from yoke_cli.transport import dispatcher as client_dispatcher

from yoke_cli.transport import https as https_transport

from yoke_core.domain import deploy_pipeline, deploy_pipeline_control_plane


def _admin_driver_env(monkeypatch, plane) -> None:
    """The candidate driver's own ambient identity: an admin door, no https."""
    monkeypatch.setenv("YOKE_ENV", "prod-db-admin")
    monkeypatch.setenv("YOKE_ACTOR_ID", str(plane["owner_id"]))
    monkeypatch.setattr(
        client_dispatcher, "_resolve_session_id", lambda: plane["owner_session"]
    )
    monkeypatch.setattr(deploy_pipeline, "resolve_project_checkout_path", lambda _p: "")


def _bootstrap_admin_env(monkeypatch, plane) -> None:
    """The admin driver with no https plane reachable at all — not even named."""
    _admin_driver_env(monkeypatch, plane)
    monkeypatch.setattr(
        https_transport, "resolve_https_connection", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        https_transport,
        "relay_https",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("local admin bootstrap contacted the serving API")
        ),
    )
