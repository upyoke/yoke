"""The CLI marks its adapter run when the control plane is reached over https."""

from __future__ import annotations

import pytest

from yoke_cli import main as cli_main
from yoke_contracts.control_plane_locality import (
    RemoteControlPlaneConnectionError,
    refuse_direct_connection,
    remote_control_plane_active,
)
from yoke_contracts.control_plane_locality import PG_DSN_ENV
from yoke_contracts.machine_config.schema import TRANSPORT_HTTPS


def _connection(monkeypatch, transport, *, raises=None):
    monkeypatch.delenv(PG_DSN_ENV, raising=False)
    def active_connection(*_args, **_kwargs):
        if raises is not None:
            raise raises
        return {"transport": transport, "env": "an-env"}

    monkeypatch.setattr(
        cli_main.machine_config, "active_connection", active_connection,
    )


def _run(monkeypatch, adapter):
    monkeypatch.setattr(
        cli_main, "resolve", lambda argv: (("probe",), "probe.run", adapter, []),
    )
    return cli_main.main(["probe"])


def test_https_connection_marks_the_adapter_run(monkeypatch) -> None:
    _connection(monkeypatch, TRANSPORT_HTTPS)
    observed: list[bool] = []
    assert _run(monkeypatch, lambda _rest: observed.append(
        remote_control_plane_active()
    ) or 0) == 0
    assert observed == [True]


def test_local_connection_leaves_the_adapter_run_unmarked(monkeypatch) -> None:
    _connection(monkeypatch, "postgres")
    observed: list[bool] = []
    assert _run(monkeypatch, lambda _rest: observed.append(
        remote_control_plane_active()
    ) or 0) == 0
    assert observed == [False]


def test_unreadable_machine_config_leaves_the_run_unmarked(monkeypatch) -> None:
    # A config problem is reported by the surfaces that already report it;
    # it says nothing about whether a local database exists.
    _connection(monkeypatch, TRANSPORT_HTTPS, raises=RuntimeError("no config"))
    observed: list[bool] = []
    assert _run(monkeypatch, lambda _rest: observed.append(
        remote_control_plane_active()
    ) or 0) == 0
    assert observed == [False]


def test_the_mark_does_not_outlive_the_invocation(monkeypatch) -> None:
    _connection(monkeypatch, TRANSPORT_HTTPS)
    _run(monkeypatch, lambda _rest: 0)
    assert remote_control_plane_active() is False


def test_a_pinned_dsn_settles_locality_before_the_machine_config(
    monkeypatch,
) -> None:
    # An explicit pin names a database to open, so the declared transport
    # does not describe this invocation — the break-glass admin shape, and
    # the shape every test run uses.
    _connection(monkeypatch, TRANSPORT_HTTPS)
    monkeypatch.setenv(PG_DSN_ENV, "host=localhost dbname=yoke_test_x")
    observed: list[bool] = []
    assert _run(monkeypatch, lambda _rest: observed.append(
        remote_control_plane_active()
    ) or 0) == 0
    assert observed == [False]


def test_an_adapter_opening_a_connection_over_https_is_refused(
    monkeypatch,
) -> None:
    _connection(monkeypatch, TRANSPORT_HTTPS)

    def adapter(_rest):
        refuse_direct_connection("db_backend.connect()")
        return 0

    with pytest.raises(RemoteControlPlaneConnectionError):
        _run(monkeypatch, adapter)
