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


def _ok_readiness():
    return SimpleNamespace(
        status=lambda: SimpleNamespace(ok=True, message=""),
        ensure_ready=lambda force=False: SimpleNamespace(ok=True, message=""),
        TunnelReplacementContended=type("TunnelReplacementContended", (Exception,), {}),
    )


def _import_with_readiness(monkeypatch, readiness, *, forbid_https_probe=False):
    real_import = local_runtime.importlib.import_module
    seen: list[str] = []

    def import_module(name: str):
        seen.append(name)
        if name == "yoke_core.domain.connected_env_readiness":
            if forbid_https_probe:
                raise AssertionError("HTTPS merge must not probe a local tunnel")
            return readiness
        return real_import(name)

    monkeypatch.setattr(local_runtime.importlib, "import_module", import_module)
    return seen


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
    seen = _import_with_readiness(monkeypatch, _ok_readiness(), forbid_https_probe=True)

    with local_runtime.same_universe_control_plane_authority() as selection:
        assert selection == ("prod", "prod")
    assert os.environ.get(ENV_OVERRIDE) == "prod"
    assert "yoke_core.domain.connected_env_readiness" not in seen


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
    seen = _import_with_readiness(monkeypatch, _ok_readiness(), forbid_https_probe=True)

    with local_runtime.same_universe_control_plane_authority() as selection:
        assert selection == ("prod", "prod")
    assert os.environ.get(ENV_OVERRIDE) == "prod"
    assert "yoke_core.domain.connected_env_readiness" not in seen


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
    seen = _import_with_readiness(monkeypatch, _ok_readiness())

    with local_runtime.same_universe_control_plane_authority() as selection:
        assert selection == ("prod-db-admin", "prod-db-admin")
    assert os.environ.get(ENV_OVERRIDE) == "prod-db-admin"
    assert "yoke_core.domain.connected_env_readiness" in seen


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
    seen = _import_with_readiness(monkeypatch, _ok_readiness())

    with local_runtime.same_universe_control_plane_authority() as selection:
        assert selection == ("local", "local")
    assert os.environ.get(ENV_OVERRIDE) == "local"
    assert "yoke_core.domain.connected_env_readiness" in seen


def test_unreachable_local_postgres_refuses_before_the_engine_loads(
    monkeypatch,
) -> None:
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

    class Contended(Exception):
        timeout = 8
        local_port = 5433
        holder = "other"

    readiness = SimpleNamespace(
        status=lambda: SimpleNamespace(ok=False, message="tunnel down"),
        ensure_ready=lambda force=False: (_ for _ in ()).throw(Contended("busy")),
        TunnelReplacementContended=Contended,
    )
    _import_with_readiness(monkeypatch, readiness)

    with pytest.raises(local_runtime.LocalMergeControlPlaneAuthorityError) as raised:
        with local_runtime.same_universe_control_plane_authority():
            pytest.fail("an unreachable local Postgres must not be yielded")

    message = str(raised.value)
    assert "local" in message
    assert "tunnel replacement stayed busy" in message


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
