# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

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
