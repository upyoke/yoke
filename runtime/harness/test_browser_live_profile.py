"""Live verification binds only the loopback endpoint in the exact profile."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread

import pytest

from yoke_harness import browser_live_profile as live

EXPECTED_PATH = "/devtools/browser/01234567-89ab-cdef-0123-456789abcdef"
OTHER_PATH = "/devtools/browser/01234567-89ab-cdef-4321-456789abcdef"


@pytest.fixture()
def metadata_server():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            assert self.path == "/json/version"
            payload = json.dumps(
                {"webSocketDebuggerUrl": self.server.endpoint}
            ).encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(payload)

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        worker = Thread(target=server.serve_forever)
        worker.start()
        try:
            yield server
        finally:
            server.shutdown()
            worker.join()


def _record(profile, port, path=EXPECTED_PATH):
    (profile / "DevToolsActivePort").write_text(f"{port}\n{path}\n", encoding="utf-8")


def test_the_live_endpoint_matches_the_exact_profile(tmp_path, metadata_server):
    port = metadata_server.server_port
    metadata_server.endpoint = f"ws://127.0.0.1:{port}{EXPECTED_PATH}"
    _record(tmp_path, port)

    assert live.live_profile_endpoint(tmp_path) == metadata_server.endpoint


@pytest.mark.parametrize("url", [
    f"ws://127.0.0.1:{{port}}{OTHER_PATH}",
    f"ws://example.invalid:{{port}}{EXPECTED_PATH}",
])
def test_a_reused_port_or_non_loopback_endpoint_is_never_attached(
    tmp_path, metadata_server, monkeypatch, url,
):
    port = metadata_server.server_port
    metadata_server.endpoint = url.format(port=port)
    _record(tmp_path, port)
    monkeypatch.setattr(live, "_profile_in_use", lambda profile: True)
    with pytest.raises(live.LiveProfileError, match="sign-in could not be verified"):
        live.live_profile_endpoint(tmp_path)
    monkeypatch.setattr(live, "_profile_in_use", lambda profile: False)
    assert live.live_profile_endpoint(tmp_path) is None


def test_open_profile_without_an_endpoint_names_the_recovery(tmp_path, monkeypatch):
    monkeypatch.setattr(live, "_profile_in_use", lambda profile: True)
    with pytest.raises(live.LiveProfileError, match="Finish any open approvals"):
        live.live_profile_endpoint(tmp_path)
