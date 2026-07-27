"""Loopback host, port, and private URL tests for the universe UI server."""

import socket

import pytest

from yoke_core.ui import server as ui_server


class TestPortProbe:
    def test_default_port_is_probed_free_or_refused(self):
        # Occupy an ephemeral port, then ask the resolver for exactly it.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as holder:
            holder.bind(("127.0.0.1", 0))
            holder.listen(1)
            taken = holder.getsockname()[1]
            with pytest.raises(ui_server.UiServerError, match="--port"):
                ui_server.resolve_ui_port(taken)

    def test_explicit_free_port_round_trips(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            free_port = probe.getsockname()[1]
        assert ui_server.resolve_ui_port(free_port) == free_port

    def test_out_of_range_port_refused(self):
        with pytest.raises(ui_server.UiServerError, match="between"):
            ui_server.resolve_ui_port(70000)

    def test_port_zero_refused_not_silently_defaulted(self):
        with pytest.raises(ui_server.UiServerError, match="between"):
            ui_server.resolve_ui_port(0)

    def test_private_url_carries_the_token(self):
        url = ui_server.private_url(1234, "s3cret")
        assert url == "http://127.0.0.1:1234/?token=s3cret"

    def test_private_url_accepts_localhost(self):
        url = ui_server.private_url(1234, "s3cret", host="localhost")
        assert url == "http://localhost:1234/?token=s3cret"

    def test_remote_facing_host_refused(self):
        with pytest.raises(ui_server.UiServerError, match="loopback-only"):
            ui_server.resolve_ui_host("0.0.0.0")
