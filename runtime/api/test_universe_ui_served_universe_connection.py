"""A served view answers from the database it was pointed at, or refuses.

The failure this pins: a view server stood up in a process whose
credential env vars named a freshly seeded database rendered the LIVE
backlog instead, because the transport is keyed to the connection
binding and the ambient binding was https. The page was real, the server
was real, the screenshot was real; only the provenance was wrong, and no
reviewer could see it in the image.

Two properties close that. The server refuses a connection it would only
relay over, so the capture cannot come from a universe nobody named; and
the connection it does serve is named in the page, so a reviewer reads
which one answered instead of trusting that it was the right one.
"""

from __future__ import annotations

import pytest

from yoke_contracts.machine_config.schema_transport import (
    DEFAULT_TRANSPORT,
    POSTGRES_TRANSPORTS,
    TRANSPORT_HTTPS,
)
from yoke_core.domain import db_backend, yoke_connected_env
from yoke_core.ui import proxy_transport, served_universe_connection
from yoke_core.ui import server as ui_server

_TOKEN = "test-session-token-value"


class _Binding:
    """The fields the guard and the transport both read off a binding.

    ``backend`` is derived the way ``load_active`` derives it, so a
    binding that reads as local-postgres here reads that way to the
    transport too — the agreement these tests assert must come from the
    code under test, never from a fixture that hardcodes both sides.
    """

    def __init__(self, *, environment: str, transport: str, prod: bool = False):
        self.environment = environment
        self.backend = (
            db_backend.POSTGRES
            if transport in POSTGRES_TRANSPORTS
            else transport
        )
        self.config = {"env": environment, "transport": transport, "prod": prod}
        self.binding_path = None


@pytest.fixture()
def bind(monkeypatch):
    """Install one connection binding as the machine's active one."""

    def _bind(binding):
        monkeypatch.setattr(
            yoke_connected_env, "load_active", lambda *a, **k: binding,
        )
        # The recipe's env inventory is not what these tests are about;
        # the refusal must stand without a readable config either way.
        monkeypatch.setattr(
            "yoke_core.domain.machine_config.load_config",
            lambda *a, **k: {"connections": {"local-dev": {
                "transport": DEFAULT_TRANSPORT,
            }}},
        )
        return binding

    return _bind


LOCAL = _Binding(environment="local-dev", transport=DEFAULT_TRANSPORT)
HOSTED = _Binding(environment="prod", transport=TRANSPORT_HTTPS)
PROD_POSTGRES = _Binding(
    environment="prod-db-admin", transport=DEFAULT_TRANSPORT, prod=True,
)


class TestTheServerRefusesAUniverseItWouldOnlyRelayTo:
    def test_an_https_binding_refuses_before_a_page_can_be_served(self, bind):
        bind(HOSTED)

        with pytest.raises(ui_server.UiServerError) as refusal:
            ui_server.create_ui_app(_TOKEN)

        message = str(refusal.value)
        assert "'prod'" in message
        assert "https-transport" in message
        # A refusal that does not say how to render honestly just moves
        # the hand-assembly one step later.
        assert "YOKE_ENV=local-dev yoke ui up" in message

    def test_a_prod_flagged_postgres_binding_refuses(self, bind):
        bind(PROD_POSTGRES)

        with pytest.raises(ui_server.UiServerError) as refusal:
            ui_server.create_ui_app(_TOKEN)

        assert "prod-flagged" in str(refusal.value)

    def test_an_unrecognized_transport_fails_closed(self, bind):
        bind(_Binding(environment="future", transport="quantum-relay"))

        with pytest.raises(ui_server.UiServerError) as refusal:
            ui_server.create_ui_app(_TOKEN)

        assert "quantum-relay" in str(refusal.value)

    def test_an_unreadable_binding_refuses_rather_than_guessing(
        self, monkeypatch,
    ):
        def _unreadable(*args, **kwargs):
            raise yoke_connected_env.ConnectedEnvError("binding unreadable")

        monkeypatch.setattr(yoke_connected_env, "load_active", _unreadable)

        with pytest.raises(ui_server.UiServerError) as refusal:
            ui_server.create_ui_app(_TOKEN)

        assert "cannot state which universe" in str(refusal.value)

    def test_importing_the_server_does_not_skip_the_refusal(self, bind):
        """The gate in `yoke ui` is a preflight, not the enforcement.

        The capture that started this was taken from a server stood up by
        importing this module directly, which never ran that command.
        """
        bind(HOSTED)

        with pytest.raises(ui_server.UiServerError):
            ui_server.serve_ui(port=0, token=_TOKEN, open_browser=False)


class TestTheServedConnectionIsTheOneTheDispatcherReads:
    @pytest.mark.parametrize(
        "binding", [LOCAL, HOSTED, PROD_POSTGRES],
        ids=lambda b: b.environment,
    )
    def test_the_guard_refuses_exactly_what_the_transport_would_relay(
        self, bind, binding,
    ):
        """Both read one authority, so neither can admit what the other
        would route elsewhere. A guard resolving the connection its own
        way is a guard that can permit a view whose reads still relay."""
        bind(binding)
        _, refusal = served_universe_connection.serving_connection()

        if proxy_transport.relays_to_server():
            assert refusal is not None

    def test_a_local_postgres_binding_is_served(self, bind):
        bind(LOCAL)

        environment, refusal = served_universe_connection.serving_connection()

        assert refusal is None
        assert environment == "local-dev"
        assert proxy_transport.relays_to_server() is False

    def test_an_unbound_process_still_serves(self, bind):
        """No binding is a test run and a config-less local universe both.
        Neither relays, so neither is the failure being prevented."""
        bind(None)

        assert served_universe_connection.serving_connection() == ("", None)


class TestThePageNamesTheUniverseThatAnswered:
    def test_the_served_shell_carries_the_environment(self, bind):
        from fastapi.testclient import TestClient

        bind(LOCAL)
        with TestClient(ui_server.create_ui_app(_TOKEN)) as client:
            shell = client.get(f"/?token={_TOKEN}").text

        # The footer renders this field, so the env reaches the frame a
        # screenshot captures rather than only a log the image omits.
        assert "local universe: local-dev" in shell

    def test_an_unnamed_environment_claims_nothing(self):
        """With no binding there is no env to show. Inventing one would
        be the same unfounded claim the label exists to retire."""
        assert served_universe_connection.environment_display_label("") is None
