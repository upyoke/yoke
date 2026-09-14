"""HTTPS-only merge keeps the selected control plane.

Ordinary hosted merge does not substitute a paired admin sibling. Local
Postgres stays local. A missing sibling is not a refusal, and ``--help``
does not require database or GitHub connectivity.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from yoke_cli.commands import merge_item_local_runtime as local_runtime
from yoke_contracts.machine_config.schema import ENV_OVERRIDE


def _connections(monkeypatch, connections: dict) -> None:
    monkeypatch.setattr(
        local_runtime.machine_config,
        "load_config",
        lambda _config_path=None: {"connections": connections},
    )


def test_https_with_sibling_stays_on_https(monkeypatch) -> None:
    _connections(
        monkeypatch,
        {
            "prod": {"transport": "https"},
            "prod-db-admin": {"transport": "local-postgres"},
        },
    )
    monkeypatch.setenv(ENV_OVERRIDE, "prod")
    monkeypatch.setattr(
        local_runtime.machine_config,
        "active_env",
        lambda: "prod",
    )
    monkeypatch.setattr(
        local_runtime.machine_config,
        "active_connection",
        lambda: {"transport": "https"},
    )

    with local_runtime.same_universe_control_plane_authority() as selection:
        assert selection == ("prod", "prod")
    assert os.environ.get(ENV_OVERRIDE) == "prod"


def test_https_without_sibling_stays_on_https(monkeypatch) -> None:
    _connections(monkeypatch, {"prod": {"transport": "https"}})
    monkeypatch.setenv(ENV_OVERRIDE, "prod")
    monkeypatch.setattr(
        local_runtime.machine_config,
        "active_env",
        lambda: "prod",
    )
    monkeypatch.setattr(
        local_runtime.machine_config,
        "active_connection",
        lambda: {"transport": "https"},
    )

    with local_runtime.same_universe_control_plane_authority() as selection:
        assert selection == ("prod", "prod")
    assert os.environ.get(ENV_OVERRIDE) == "prod"


def test_explicit_admin_postgres_stays_on_the_selected_connection(monkeypatch) -> None:
    _connections(
        monkeypatch,
        {
            "prod": {"transport": "https"},
            "prod-db-admin": {"transport": "local-postgres"},
        },
    )
    monkeypatch.setenv(ENV_OVERRIDE, "prod-db-admin")
    monkeypatch.setattr(
        local_runtime.machine_config,
        "active_env",
        lambda: "prod-db-admin",
    )
    monkeypatch.setattr(
        local_runtime.machine_config,
        "active_connection",
        lambda: {"transport": "local-postgres"},
    )

    with local_runtime.same_universe_control_plane_authority() as selection:
        assert selection == ("prod-db-admin", "prod-db-admin")
    assert os.environ.get(ENV_OVERRIDE) == "prod-db-admin"


def test_a_local_postgres_connection_is_never_switched(monkeypatch) -> None:
    _connections(
        monkeypatch,
        {"local": {"transport": "local-postgres"}},
    )
    monkeypatch.setenv(ENV_OVERRIDE, "local")
    monkeypatch.setattr(
        local_runtime.machine_config,
        "active_env",
        lambda: "local",
    )
    monkeypatch.setattr(
        local_runtime.machine_config,
        "active_connection",
        lambda: {"transport": "local-postgres"},
    )

    with local_runtime.same_universe_control_plane_authority() as selection:
        assert selection == ("local", "local")
    assert os.environ.get(ENV_OVERRIDE) == "local"


def test_unsupported_transport_refuses(monkeypatch) -> None:
    monkeypatch.setattr(
        local_runtime.machine_config,
        "active_env",
        lambda: "odd",
    )
    monkeypatch.setattr(
        local_runtime.machine_config,
        "active_connection",
        lambda: {"transport": "ssh"},
    )

    with pytest.raises(local_runtime.LocalMergeControlPlaneAuthorityError) as raised:
        with local_runtime.same_universe_control_plane_authority():
            pytest.fail("an unsupported transport must not be yielded")

    message = str(raised.value)
    assert "unsupported transport" in message
    assert "odd" in message


def test_help_skips_github_and_control_plane_authority(monkeypatch) -> None:
    seen: list[list[str]] = []

    def fail_config(*_a, **_k):
        raise local_runtime.machine_config.MachineConfigError("offline")

    monkeypatch.setattr(local_runtime.machine_config, "load_config", fail_config)
    monkeypatch.setattr(local_runtime.machine_config, "active_env", fail_config)
    monkeypatch.setattr(local_runtime.machine_config, "active_connection", fail_config)
    monkeypatch.setattr(
        local_runtime.merge_path_binding,
        "resolve_selection",
        lambda: pytest.fail("help must not bind GitHub"),
    )

    real_import = local_runtime.importlib.import_module

    def import_module(name: str):
        if name == "yoke_core.domain.standalone_item_merge_cli":
            return SimpleNamespace(main=lambda argv: seen.append(list(argv)) or 0)
        return real_import(name)

    monkeypatch.setattr(local_runtime.importlib, "import_module", import_module)

    assert local_runtime.main(["--help"]) == 0
    assert seen == [["--help"]]
