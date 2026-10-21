"""Private HTTP connects, published binds and real credential-bearing requests."""

import io
import json
import socket
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from yoke_cli.commands import connect, self_host
from yoke_cli.config import server_connect
from yoke_cli.transport.bounded_json_http import request_json
from yoke_contracts.machine_authorization import authorization_origin
from yoke_contracts.machine_approval_coordinates import machine_approval_coordinates
from yoke_contracts.private_network_http import allows_http_host


PRIVATE_HOSTS = [
    "10.0.0.0",
    "10.255.255.255",
    "172.16.0.0",
    "172.31.255.255",
    "192.168.0.0",
    "192.168.255.255",
    "100.64.0.0",
    "100.127.255.255",
    "fd00::1",
    "fdff:ffff::1",
    "server.team.ts.net",
    "SERVER.TS.NET.",
]


@pytest.mark.parametrize("host", PRIVATE_HOSTS)
def test_private_http_connect_warns_every_time_and_persists(
    monkeypatch, tmp_path, capsys, host
):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path))
    monkeypatch.setattr(
        server_connect, "_http_get_json", lambda *a, **kw: {"status": "ok"}
    )
    url = f"http://[{host}]:8765" if ":" in host else f"http://{host}:8765"
    assert allows_http_host(host)
    assert authorization_origin(url) == url
    assert machine_approval_coordinates(url + "/machine/K7F2", "K7F2").origin == url
    for _ in range(2):
        monkeypatch.setattr(sys, "stdin", io.StringIO("test-private-token"))
        assert connect.connect([url, "--token-stdin", "--json"]) == 0
        output = capsys.readouterr()
        assert "private_network_http" in output.err
        assert "unencrypted" in output.err
        assert "test-private-token" not in output.err + output.out
        assert json.loads(output.out)["api_url"] == url
    config = json.loads((tmp_path / "config.json").read_text())
    assert config["connections"]["self-host"]["api_url"] == url


@pytest.mark.parametrize(
    "host",
    [
        "9.255.255.255",
        "11.0.0.0",
        "172.15.255.255",
        "172.32.0.0",
        "192.167.255.255",
        "192.169.0.0",
        "100.63.255.255",
        "100.128.0.0",
        "fc00::1",
        "fe80::1",
        "2001:4860::1",
        "0.0.0.0",
        "::",
        "ts.net",
        "server.ts.net.evil.example",
        "localhost",
        "yoke.internal",
    ],
)
def test_public_http_refused_before_network_or_config(
    monkeypatch, tmp_path, capsys, host
):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path))
    monkeypatch.setattr(
        server_connect, "_http_get_json", lambda *a, **kw: pytest.fail("network used")
    )
    url = f"http://[{host}]" if ":" in host else f"http://{host}"
    assert not allows_http_host(host)
    assert connect.connect([url, "--token-stdin"]) == 1
    assert "public_http_refused" in capsys.readouterr().err
    assert not (tmp_path / "config.json").exists()


@pytest.mark.usefixtures("installed_self_host_prerequisites")
@pytest.mark.parametrize(
    "host, publish",
    [
        (None, "127.0.0.1:9876"),
        ("100.101.102.103", "100.101.102.103:9876"),
        ("192.168.1.8", "192.168.1.8:9876"),
        ("0.0.0.0", "0.0.0.0:9876"),
        ("fd00::123", "[fd00::123]:9876"),
    ],
)
def test_listen_writes_existing_publish_setting_and_teammate_command(
    tmp_path, capsys, host, publish
):
    args = [
        "--admin-name",
        "Server Owner",
        "--dir",
        str(tmp_path),
        "--port",
        "9876",
        "--image",
        "example.invalid/yoke@sha256:" + "a" * 64,
    ]
    if host:
        args += ["--listen", host]
    assert self_host.self_host_init(args) == 0
    assert f"YOKE_API_PUBLISH={publish}" in (tmp_path / ".env").read_text()
    output = capsys.readouterr()
    if host is None:
        assert "--listen ADDRESS" in output.out
    elif host == "0.0.0.0":
        assert "yoke connect http://<server-private-address>:9876" in output.out
    else:
        assert f"yoke connect http://{publish}" in output.out


@pytest.mark.usefixtures("installed_self_host_prerequisites")
@pytest.mark.parametrize("host", ["host.internal", "10.0.0.1:8765", "bad\nvalue"])
def test_invalid_listen_is_diagnosed_without_writes(tmp_path, capsys, host):
    target = tmp_path / "bundle"
    assert (
        self_host.self_host_init(
            ["--admin-name", "Owner", "--dir", str(target), "--listen", host]
        )
        == 1
    )
    assert "listen_address_invalid" in capsys.readouterr().err
    assert not target.exists()


@pytest.mark.parametrize("host", ["100.101.102.103", "server.team.ts.net", "fd00::123"])
def test_real_http_get_and_post_bypass_proxy_and_keep_credentials_on_target(
    monkeypatch, tmp_path, host
):
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.respond()

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            self.respond()

        def respond(self):
            seen.append((self.command, self.path, self.headers.get("Authorization")))
            body = b'{"status":"ok"}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    real_resolve = socket.getaddrinfo

    def resolve(name, port, *args, **kwargs):
        return real_resolve(
            "127.0.0.1" if name == host else name, port, *args, **kwargs
        )

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:1")
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path))
    rendered = f"[{host}]" if ":" in host else host
    url = f"http://{rendered}:{server.server_port}"
    try:
        assert server_connect.connect_server(url, token="private-test")["ok"]
        response = request_json(
            urllib.request.Request(
                url + "/mutation",
                data=b"{}",
                headers={"Authorization": "Bearer private-test"},
            ),
            timeout_seconds=2,
            replay_safe=False,
            allow_private_http=True,
        )
        assert response.payload["status"] == "ok"
        assert seen == [
            ("GET", "/v1/health", None),
            ("GET", "/v1/auth/identity", "Bearer private-test"),
            ("POST", "/mutation", "Bearer private-test"),
        ]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
