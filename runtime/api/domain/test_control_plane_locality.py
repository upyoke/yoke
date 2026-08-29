"""The connection factory refuses a direct connect where the control plane is remote."""

from __future__ import annotations

import threading

import pytest

from yoke_contracts.control_plane_locality import (
    RemoteControlPlaneConnectionError,
    local_authority_exempt,
    refuse_direct_connection,
    remote_control_plane,
    remote_control_plane_active,
)
from yoke_core.domain import backlog_github_done_sync
from yoke_core.domain import control_plane_transport, db_backend
from yoke_core.domain import project_github_auth_state, yok_n_parser
from yoke_core.domain.db_helpers import connect as db_helpers_connect


def test_unmarked_context_admits_a_direct_connection() -> None:
    # A server process and a local-Postgres machine both hold the authority
    # they are connecting to, so neither marks the context.
    assert remote_control_plane_active() is False
    refuse_direct_connection("anything")


def test_marked_context_refuses_and_names_both_ways_out() -> None:
    with remote_control_plane():
        assert remote_control_plane_active() is True
        with pytest.raises(RemoteControlPlaneConnectionError) as raised:
            refuse_direct_connection("db_backend.connect()")
    message = str(raised.value)
    assert "db_backend.connect()" in message
    assert "relay" in message
    assert "local_authority_exempt" in message


def test_mark_is_restored_after_the_block() -> None:
    with remote_control_plane():
        pass
    assert remote_control_plane_active() is False


def test_exemption_admits_the_connection_then_restores_the_mark() -> None:
    with remote_control_plane():
        with local_authority_exempt():
            assert remote_control_plane_active() is False
            refuse_direct_connection("declared local open")
        assert remote_control_plane_active() is True


def test_blanket_except_exception_cannot_swallow_the_refusal() -> None:
    # The instance that motivates this: a bare connection inside a blanket
    # except that returned False, so the write it skipped surfaced nowhere.
    def swallowing_caller() -> bool:
        try:
            refuse_direct_connection("db_backend.connect()")
            return True
        except Exception:  # noqa: BLE001 - the shape under test
            return False

    with remote_control_plane():
        with pytest.raises(RemoteControlPlaneConnectionError):
            swallowing_caller()


def test_one_thread_marking_does_not_mark_another() -> None:
    # The reason this is a ContextVar and not an environment variable: a
    # server relays many requests through one process.
    observed: list[bool] = []
    started = threading.Event()
    release = threading.Event()

    def other_thread() -> None:
        started.set()
        release.wait(timeout=5)
        observed.append(remote_control_plane_active())

    worker = threading.Thread(target=other_thread)
    worker.start()
    started.wait(timeout=5)
    with remote_control_plane():
        release.set()
        worker.join(timeout=5)
    assert observed == [False]


def test_ambient_factory_calls_refuse_before_resolving_anything() -> None:
    with remote_control_plane():
        with pytest.raises(RemoteControlPlaneConnectionError):
            db_backend.connect()
        with pytest.raises(RemoteControlPlaneConnectionError):
            db_backend.connect_psycopg()
        with pytest.raises(RemoteControlPlaneConnectionError):
            db_helpers_connect()


def test_explicit_dsn_names_its_own_database_and_is_admitted(monkeypatch) -> None:
    import psycopg

    opened: list[str] = []
    monkeypatch.setattr(
        psycopg, "connect", lambda target, **kwargs: opened.append(target) or object(),
    )
    with remote_control_plane():
        db_backend.connect_psycopg("host=elsewhere dbname=validation")
    assert opened == ["host=elsewhere dbname=validation"]


def test_local_first_probe_still_attempts_the_connection() -> None:
    # The probe's whole job is to try; a refusal there would answer the
    # question the attempt is asking.
    attempts: list[bool] = []

    def attempt():
        attempts.append(remote_control_plane_active())
        raise RuntimeError("no local Postgres here")

    with remote_control_plane():
        assert control_plane_transport.local_connection_or_none(attempt) is None
    assert attempts == [False]


def test_reintroduced_bare_connection_on_a_client_path_fires(monkeypatch) -> None:
    # The shape three confirmed instances shared: reach the shared GitHub
    # binding-state reader by opening a connection instead of probing first.
    def bare_reader(project: str):
        conn = db_helpers_connect(None)
        return project_github_auth_state.read_github_state_over_connection(
            conn, project,
        )

    with remote_control_plane():
        with pytest.raises(RemoteControlPlaneConnectionError):
            bare_reader("yoke")


def test_the_repaired_reader_relays_instead_of_refusing(monkeypatch) -> None:
    # Stand in for the machine this is about: no local Postgres to open, so
    # the probe comes back empty and the read has to relay.
    def no_local_authority(_db_path=None):
        raise RuntimeError("no local Postgres here")

    monkeypatch.setattr(project_github_auth_state, "connect", no_local_authority)

    relayed: list[tuple[str, dict]] = []

    def fake_relay(function_id: str, payload: dict) -> dict:
        relayed.append((function_id, payload))
        return {
            "project_slug": payload["project"],
            "project_id": None,
            "has_capability": False,
            "binding": None,
            "installation": None,
        }

    monkeypatch.setattr(control_plane_transport, "relay", fake_relay)

    with remote_control_plane():
        state = project_github_auth_state.read_github_state("yoke", None)

    assert relayed == [
        (project_github_auth_state.READ_FUNCTION_ID, {"project": "yoke"}),
    ]
    assert state.project_slug == "yoke"
    assert state.has_capability is False


def _no_local_authority(*_args, **_kwargs):
    raise RuntimeError("no local Postgres here")


def test_a_public_ref_resolves_without_a_local_database(monkeypatch) -> None:
    # Public refs are the reference shape every client surface accepts, so
    # resolving one must not require a database the client does not have.
    monkeypatch.setattr(yok_n_parser, "connect", _no_local_authority)
    seen: list = []

    def fake_relay(function_id, payload, target=None):
        seen.append((function_id, target.kind, target.public_ref))
        return {"item": {"id": 4242}}

    monkeypatch.setattr(control_plane_transport, "relay", fake_relay)

    with remote_control_plane():
        assert yok_n_parser.parse_item_id("YOK-7") == 4242

    assert seen == [(yok_n_parser.RESOLVE_FUNCTION_ID, "item", "YOK-7")]


def test_an_unresolvable_public_ref_still_raises_valueerror(monkeypatch) -> None:
    monkeypatch.setattr(yok_n_parser, "connect", _no_local_authority)
    monkeypatch.setattr(
        control_plane_transport,
        "relay",
        lambda *_a, **_k: {"item": {}},
    )
    with remote_control_plane():
        with pytest.raises(ValueError):
            yok_n_parser.parse_item_id("YOK-7")


def test_done_closeout_relays_instead_of_failing_the_step(monkeypatch) -> None:
    # The closeout reads the item, renders its body, and stamps sync state,
    # so it runs where the control plane is rather than degrading the step.
    monkeypatch.setattr(backlog_github_done_sync, "_connect", _no_local_authority)
    seen: list = []

    def fake_relay(function_id, payload, target=None):
        seen.append((function_id, payload, target.item_id, target.public_ref))
        return {"item_id": 4242, "exit_code": 0, "board_rebuild_requested": True}

    monkeypatch.setattr(control_plane_transport, "relay", fake_relay)

    with remote_control_plane():
        rc = backlog_github_done_sync.sync_done_item("4242", "reviewing")

    assert rc == 0
    assert seen == [
        (
            backlog_github_done_sync.DONE_SYNC_FUNCTION_ID,
            {"old_status": "reviewing"},
            4242,
            None,
        ),
    ]


def test_a_public_ref_closeout_targets_the_ref_not_a_sequence_number() -> None:
    numeric = backlog_github_done_sync._done_sync_target("4242")
    public = backlog_github_done_sync._done_sync_target("YOK-7")
    assert (numeric.item_id, numeric.public_ref) == (4242, None)
    assert (public.item_id, public.public_ref) == (None, "YOK-7")
