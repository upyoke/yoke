"""Naming the build that serves this machine's control plane.

Three answers, and only one of them is silence. An https connection is
that build's front door. A local universe is served by the process holding
its database, and "" says so. A database door whose plane this machine
cannot name owes an answer it does not have, and saying "" there would run
schema-bound work on whatever revision the caller happens to be.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import control_plane_transport


def stub_machine_connections(monkeypatch, *, active: str, connections: dict):
    """Present one machine's configured connections to the resolver."""
    from yoke_cli.config import machine_config
    from yoke_cli.transport import https as https_transport

    monkeypatch.setattr(
        https_transport, "resolve_https_connection", lambda *a, **k: None
    )
    monkeypatch.setattr(machine_config, "active_env", lambda *a, **k: active)
    monkeypatch.setattr(
        machine_config, "load_config", lambda *a, **k: {"connections": connections}
    )


def test_an_admin_env_with_no_plane_refuses_instead_of_running_here(monkeypatch):
    """The failure this replaces was silent, so the gap must not be.

    An admin connection is a door into one universe's database. When its
    https sibling is absent, this machine cannot name the build that owns
    that schema — and answering "no plane" would run the evaluation on
    whatever revision the caller happens to be, which is the defect.
    """
    stub_machine_connections(
        monkeypatch,
        active="prod-db-admin",
        connections={"prod-db-admin": {"transport": "local-postgres"}},
    )
    with pytest.raises(control_plane_transport.ServingControlPlaneUnresolved) as raised:
        control_plane_transport.serving_control_plane_env()
    message = str(raised.value)
    assert "prod-db-admin" in message
    assert "yoke connection set prod" in message


def test_an_unreadable_connection_configuration_refuses(monkeypatch):
    from yoke_cli.config import machine_config
    from yoke_cli.transport import https as https_transport

    monkeypatch.setattr(
        https_transport, "resolve_https_connection", lambda *a, **k: None
    )

    def _unreadable(*_args, **_kwargs):
        raise OSError("connections file is unreadable")

    monkeypatch.setattr(machine_config, "load_config", _unreadable)
    with pytest.raises(control_plane_transport.ServingControlPlaneUnresolved):
        control_plane_transport.serving_control_plane_env()


def test_a_broken_https_connection_refuses_rather_than_reading_as_local(
    monkeypatch,
):
    from yoke_cli.transport import https as https_transport

    def _misconfigured(*_args, **_kwargs):
        raise https_transport.TransportError("no api_url on env 'prod'")

    monkeypatch.setattr(https_transport, "resolve_https_connection", _misconfigured)
    with pytest.raises(control_plane_transport.ServingControlPlaneUnresolved):
        control_plane_transport.serving_control_plane_env()


def test_an_admin_connection_routes_to_the_plane_it_administers(monkeypatch):
    """A database door is not a plane; its https sibling is."""
    from yoke_cli.transport import https as https_transport

    monkeypatch.setattr(
        https_transport,
        "resolve_https_connection",
        lambda *a, **k: None,
    )
    from yoke_cli.config import machine_config

    monkeypatch.setattr(
        machine_config,
        "active_env",
        lambda *a, **k: "prod-db-admin",
    )
    monkeypatch.setattr(
        machine_config,
        "load_config",
        lambda *a, **k: {
            "connections": {
                "prod": {"transport": "https", "api_url": "https://example"},
                "prod-db-admin": {"transport": "local-postgres"},
            }
        },
    )
    assert control_plane_transport.serving_control_plane_env() == "prod"


def test_a_local_universe_serves_itself(monkeypatch):
    from yoke_cli.transport import https as https_transport
    from yoke_cli.config import machine_config

    monkeypatch.setattr(
        https_transport,
        "resolve_https_connection",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(machine_config, "active_env", lambda *a, **k: "local")
    monkeypatch.setattr(
        machine_config,
        "load_config",
        lambda *a, **k: {"connections": {"local": {"transport": "local-postgres"}}},
    )
    assert control_plane_transport.serving_control_plane_env() == ""
