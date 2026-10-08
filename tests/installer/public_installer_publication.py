"""Shared fixture for public-installer dry-run publication tests."""

from __future__ import annotations

import io
import json
import threading
import urllib.error
from email.message import EmailMessage
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote

from public_installer_helpers import PUBLISHED_RELEASE_RECORD, RecordingRunner
from test_public_installer import _options

MISSING_VERSION = "0.1.1+launch.999999999"


def release_path(version: str) -> str:
    return f"/dist/releases/{quote(version, safe='')}/release-records.json"


def http_error(url: str, code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url, code, "nope", hdrs=EmailMessage(), fp=io.BytesIO(b"")
    )


class ReleaseOrigin:
    def __init__(self) -> None:
        self.routes: dict[str, tuple[int, bytes]] = {}
        self.requested: list[str] = []
        origin = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
                path = self.path.split("?", 1)[0]
                origin.requested.append(path)
                status, body = origin.routes.get(path, (404, b""))
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, fmt: str, *args) -> None:
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def publish(self, version: str, body: bytes = PUBLISHED_RELEASE_RECORD) -> None:
        self.routes[release_path(version)] = (200, body)

    def channel(self, version: str, name: str = "stable") -> None:
        payload = json.dumps(
            {"schema_version": 2, "version": version, "channel": name}
        ).encode()
        self.routes[f"/dist/channels/{name}.json"] = (200, payload)


def run_cli(module, argv: list[str], capsys):
    code = module.main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def dry_run_installer(module, *, fetcher, **overrides):
    output = io.StringIO()
    runner = RecordingRunner()
    installer = module.Installer(
        _options(module, dry_run=True, yes=True, no_setup=True, **overrides),
        fetcher=fetcher,
        runner=runner,
        stdout=output,
    )
    return installer, runner, output
