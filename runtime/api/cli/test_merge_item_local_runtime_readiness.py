"""Selecting a control plane is not the same as being able to reach it.

A local merge switches from the https product connection to its same-universe
Postgres sibling, which normally sits behind an SSH forward. A forward that has
died answers the *first* dispatched call of the merge rather than the switch,
so the merge failed halfway through with a tunnel error against a control plane
that had silently moved underneath it. The switch now proves the connection
before yielding, and refuses before anything has merged.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from yoke_cli.commands import merge_item_local_runtime as local_runtime
from yoke_contracts.machine_config.schema import ENV_OVERRIDE


@pytest.fixture(autouse=True)
def _https_control_plane(monkeypatch) -> None:
    monkeypatch.setattr(
        local_runtime.machine_config,
        "load_config",
        lambda _config_path=None: {
            "connections": {
                "prod": {"transport": "https"},
                "prod-db-admin": {"transport": "local-postgres"},
            }
        },
    )
    monkeypatch.setenv(ENV_OVERRIDE, "prod")


def _readiness(monkeypatch, ensure_ready) -> None:
    real_import = local_runtime.importlib.import_module

    def import_module(name: str):
        if name == "yoke_core.domain.connected_env_readiness":
            return SimpleNamespace(ensure_ready=ensure_ready)
        return real_import(name)

    monkeypatch.setattr(local_runtime.importlib, "import_module", import_module)


def test_a_reachable_sibling_yields_the_switched_authority(monkeypatch) -> None:
    probes: list[dict] = []

    def ensure_ready(**kwargs):
        probes.append(kwargs)
        assert os.environ.get(ENV_OVERRIDE) == "prod-db-admin"
        return SimpleNamespace(ok=True, message="tunnel healthy")

    _readiness(monkeypatch, ensure_ready)

    with local_runtime.same_universe_control_plane_authority() as selection:
        assert selection == ("prod", "prod-db-admin")
    # Forced, because a cached verdict from before the network changed is
    # exactly the answer this probe exists to distrust.
    assert probes == [{"force": True}]
    assert os.environ.get(ENV_OVERRIDE) == "prod"


def test_an_unreachable_sibling_refuses_before_anything_merges(monkeypatch):
    _readiness(
        monkeypatch,
        lambda **_k: SimpleNamespace(
            ok=False, message="ssh tunnel start failed (rc=-15)",
        ),
    )

    with pytest.raises(local_runtime.LocalMergeControlPlaneAuthorityError) as raised:
        with local_runtime.same_universe_control_plane_authority():
            pytest.fail("an unreachable control plane must not be yielded")

    message = str(raised.value)
    assert "prod-db-admin" in message
    assert "ssh tunnel start failed" in message
    assert "nothing has been merged" in message
    assert os.environ.get(ENV_OVERRIDE) == "prod"


def test_a_raising_probe_is_the_same_refusal(monkeypatch) -> None:
    """``ConnectedEnvUnavailable`` and a psycopg read failure read alike here."""

    def ensure_ready(**_kwargs):
        raise RuntimeError("consuming input failed: SSL error: unexpected eof")

    _readiness(monkeypatch, ensure_ready)

    with pytest.raises(local_runtime.LocalMergeControlPlaneAuthorityError) as raised:
        with local_runtime.same_universe_control_plane_authority():
            pytest.fail("an unreachable control plane must not be yielded")

    assert "unexpected eof" in str(raised.value)
    assert os.environ.get(ENV_OVERRIDE) == "prod"


def test_a_local_postgres_connection_is_never_probed(monkeypatch) -> None:
    """Nothing is switched, so there is nothing to prove reachable."""
    monkeypatch.setattr(
        local_runtime.machine_config,
        "load_config",
        lambda _config_path=None: {
            "connections": {"local": {"transport": "local-postgres"}}
        },
    )
    monkeypatch.setenv(ENV_OVERRIDE, "local")
    _readiness(
        monkeypatch,
        lambda **_k: pytest.fail("an unswitched connection needs no probe"),
    )

    with local_runtime.same_universe_control_plane_authority() as selection:
        assert selection == ("local", "local")
