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
import threading
from types import SimpleNamespace

import pytest

from yoke_cli.commands import merge_item_local_runtime as local_runtime
from yoke_core.domain.connected_env_tunnel_coordination import (
    TunnelReplacementContended,
)
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
            return SimpleNamespace(
                ensure_ready=ensure_ready,
                status=lambda: ensure_ready(force=False),
                TunnelReplacementContended=TunnelReplacementContended,
            )
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
    assert probes == [{"force": False}]
    assert os.environ.get(ENV_OVERRIDE) == "prod"


def test_an_unreachable_sibling_refuses_before_anything_merges(monkeypatch):
    probes: list[dict] = []

    def unavailable(**kwargs):
        probes.append(kwargs)
        return SimpleNamespace(
            ok=False,
            message="ssh tunnel start failed (rc=-15)",
        )

    _readiness(
        monkeypatch,
        unavailable,
    )

    with pytest.raises(local_runtime.LocalMergeControlPlaneAuthorityError) as raised:
        with local_runtime.same_universe_control_plane_authority():
            pytest.fail("an unreachable control plane must not be yielded")

    message = str(raised.value)
    assert "prod-db-admin" in message
    assert "ssh tunnel start failed" in message
    assert "nothing has been merged" in message
    assert probes == [{"force": False}, {"force": True}]
    assert os.environ.get(ENV_OVERRIDE) == "prod"


def test_a_contended_replacement_preserves_the_wait_recovery(monkeypatch) -> None:
    force_calls = 0

    def ensure_ready(*, force: bool):
        nonlocal force_calls
        if not force:
            return SimpleNamespace(ok=False, message="probe failed")
        force_calls += 1
        raise TunnelReplacementContended(
            local_port=6547,
            timeout=180,
            holder="holder pid=81775 command='yoke deploy' held=42s",
        )

    _readiness(monkeypatch, ensure_ready)

    with pytest.raises(local_runtime.LocalMergeControlPlaneAuthorityError) as raised:
        with local_runtime.same_universe_control_plane_authority():
            pytest.fail("a contended replacement must not yield the authority")

    message = str(raised.value)
    assert "holder pid=81775" in message
    assert "command='yoke deploy'" in message
    assert "held=42s" in message
    assert "keep the named holder running" in message
    assert "Restore the connection" not in message
    assert force_calls == 2


def test_two_concurrent_merge_authority_checks_wait_and_both_continue(
    monkeypatch, capsys
) -> None:
    holder_started = threading.Event()
    contention_observed = threading.Event()
    holder_finished = threading.Event()
    contender_force_calls = 0
    successes: list[str] = []
    failures: list[BaseException] = []

    def ensure_ready(*, force: bool):
        nonlocal contender_force_calls
        if not force:
            return SimpleNamespace(ok=False, message="probe failed")
        if threading.current_thread().name == "tunnel-holder-merge":
            holder_started.set()
            assert contention_observed.wait(timeout=2)
            holder_finished.set()
            return SimpleNamespace(ok=True, message="tunnel restored")
        contender_force_calls += 1
        if contender_force_calls == 1:
            assert holder_started.wait(timeout=2)
            contention_observed.set()
            raise TunnelReplacementContended(
                local_port=6547,
                timeout=180,
                holder=("holder pid=81775 command='yoke merge item OTHER' held=180s"),
            )
        assert holder_finished.wait(timeout=2)
        return SimpleNamespace(ok=True, message="tunnel adopted")

    _readiness(monkeypatch, ensure_ready)

    def confirm(name: str) -> None:
        try:
            local_runtime._confirm_selected_control_plane("prod-db-admin")
        except BaseException as exc:  # noqa: BLE001 - asserted below
            failures.append(exc)
        else:
            successes.append(name)

    holder = threading.Thread(
        target=confirm, args=("holder",), name="tunnel-holder-merge"
    )
    contender = threading.Thread(
        target=confirm,
        args=("contender",),
        name="tunnel-contender-merge",
    )
    holder.start()
    assert holder_started.wait(timeout=2)
    contender.start()
    holder.join(timeout=2)
    contender.join(timeout=2)

    assert not holder.is_alive()
    assert not contender.is_alive()
    assert failures == []
    assert sorted(successes) == ["contender", "holder"]
    assert contender_force_calls == 2
    wait_line = capsys.readouterr().err
    assert wait_line.count("tunnel_busy") == 1
    assert "holder pid=81775" in wait_line
    assert "elapsed=180s/limit=180s" in wait_line


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
