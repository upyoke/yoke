"""Owner-only gate for deployment-run create / start-for-item."""

from __future__ import annotations

from unittest import mock

from yoke_cli.commands.adapters import deployment_owner_authority as owner
from yoke_cli.transport.https import HttpsConnection, TransportError


def test_local_postgres_connection_is_allowed():
    with mock.patch(
        "yoke_cli.transport.https.resolve_https_connection",
        return_value=None,
    ):
        assert owner.https_product_plane_create_error("create") is None


def test_https_product_plane_is_refused():
    https = HttpsConnection(
        api_url="https://example.test",
        token="t",
        env="prod",
    )
    with (
        mock.patch(
            "yoke_cli.transport.https.resolve_https_connection",
            return_value=https,
        ),
        mock.patch.object(
            owner, "_same_universe_admin_env", return_value="prod-db-admin",
        ),
    ):
        error = owner.https_product_plane_create_error("deployment-runs create")
    assert error is not None
    assert "prod-db-admin" in error
    assert "HTTPS product plane" in error
    assert "deployment-runs create" in error
    assert " or local" not in error


def test_https_gate_does_not_invent_an_unresolvable_alternative():
    https = HttpsConnection(
        api_url="https://example.test", token="t", env="prod",
    )
    with (
        mock.patch(
            "yoke_cli.transport.https.resolve_https_connection",
            return_value=https,
        ),
        mock.patch.object(owner, "_same_universe_admin_env", return_value=""),
    ):
        error = owner.https_product_plane_create_error("create")
    assert "configure a same-universe" in error
    assert "prod-db-admin" not in error
    assert " or local" not in error


def test_broken_https_connection_names_the_repair():
    with (
        mock.patch(
            "yoke_cli.transport.https.resolve_https_connection",
            side_effect=TransportError("token missing"),
        ),
        mock.patch.object(owner, "_same_universe_admin_env", return_value=""),
    ):
        error = owner.https_product_plane_create_error("start-for-item")
    assert error is not None
    assert "broken HTTPS" in error
    assert "token missing" in error
