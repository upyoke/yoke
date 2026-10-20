"""Actor lookups keep database failure distinct from an absent actor."""

from unittest.mock import Mock

import psycopg
import pytest

from runtime.api.domain.test_session_less_actor_binding import _entry, _request
from yoke_core.domain import yoke_function_actor_identity as identity
from yoke_core.domain.deployment_driver_identity import driver_identity_operation
from yoke_core.domain.deploy_pipeline_unknown_outcome import preserve_unknown_outcome
from yoke_core.domain.function_connection_loss import CONNECTION_LOST_CODE
from yoke_core.domain.connected_env_readiness_connector import (
    looks_like_connection_failure,
)


@pytest.mark.parametrize("error", [psycopg.OperationalError, psycopg.InterfaceError])
def test_closed_connection_is_classified(error):
    assert looks_like_connection_failure(error("the connection is closed"))


@pytest.mark.parametrize("session", ["", "bound-session"])
def test_actor_database_failure_is_named_connection_loss(monkeypatch, session):
    conn = Mock()
    conn.execute.side_effect = psycopg.OperationalError("the connection is closed")
    monkeypatch.setattr(
        "yoke_core.domain.control_plane_transport.local_connection_or_none",
        lambda *a, **k: conn,
    )
    if not session:
        monkeypatch.setattr(
            "yoke_core.domain.session_actor_binding.resolve_operating_actor",
            Mock(side_effect=psycopg.OperationalError("the connection is closed")),
        )
    request = _request()
    request.actor.session_id = session
    result = identity.bind_actor_identity(_entry(), request, ambient_session_id=session)
    assert result.error.error.code == CONNECTION_LOST_CODE
    assert "Re-read" in result.error.error.message
    conn.close.assert_called_once()


def test_successful_driver_identity_is_read_once_and_scope_is_released(monkeypatch):
    lookup = Mock(return_value=identity.ActorLookup("2", True))
    monkeypatch.setattr(identity, "_load_actor_lookup", lookup)
    monkeypatch.setattr(
        "yoke_core.domain.session_ambient_identity.resolve_ambient_session_id",
        lambda: "driver",
    )

    @driver_identity_operation
    def drive(run_id):
        for _ in range(4):
            assert identity._default_actor_id_resolver("driver").actor_id == "2"
        return 0

    assert drive("run-test") == 0
    lookup.assert_called_once_with("driver")
    identity._default_actor_id_resolver("driver")
    assert lookup.call_count == 2


def test_lookup_drop_stops_driver_without_failure_write(monkeypatch, capsys):
    monkeypatch.setattr(
        "yoke_core.domain.session_ambient_identity.resolve_ambient_session_id",
        lambda: "driver",
    )
    monkeypatch.setattr(
        identity,
        "_load_actor_lookup",
        Mock(side_effect=psycopg.OperationalError("the connection is closed")),
    )
    drive = Mock(return_value=0)
    assert preserve_unknown_outcome(driver_identity_operation(drive))("run-test") == 1
    drive.assert_not_called()
    assert "deployment_outcome_unknown" in capsys.readouterr().err


def test_driver_does_not_misclassify_a_query_defect_as_an_actor_drop(monkeypatch):
    monkeypatch.setattr(
        identity, "_load_actor_lookup", lambda _: identity.ActorLookup("2", True)
    )
    monkeypatch.setattr(
        "yoke_core.domain.session_ambient_identity.resolve_ambient_session_id",
        lambda: "driver",
    )

    @driver_identity_operation
    def drive(run_id):
        raise psycopg.errors.UndefinedTable("a query names an absent table")

    with pytest.raises(psycopg.errors.UndefinedTable):
        drive("run-test")
