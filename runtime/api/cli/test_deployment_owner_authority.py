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
    with mock.patch(
        "yoke_cli.transport.https.resolve_https_connection",
        return_value=https,
    ):
        error = owner.https_product_plane_create_error("deployment-runs create")
    assert error is not None
    assert "prod-db-admin" in error
    assert "HTTPS product plane" in error
    assert "deployment-runs create" in error


def test_broken_https_connection_names_the_repair():
    with mock.patch(
        "yoke_cli.transport.https.resolve_https_connection",
        side_effect=TransportError("token missing"),
    ):
        error = owner.https_product_plane_create_error("start-for-item")
    assert error is not None
    assert "broken HTTPS" in error
    assert "token missing" in error
