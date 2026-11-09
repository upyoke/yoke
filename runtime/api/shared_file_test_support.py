"""An in-process object store that honors presigned-URL expiry.

Shared-file tests sign against this store instead of S3: ``sign`` returns a
URL carrying its absolute expiry, and the store refuses a request after that
instant with HTTP 403, as S3 does. ``advance`` moves the store's clock so a
test can prove a stable read URL survives the expiry of every signed link.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Iterator
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from runtime.api.qa_artifact_read_test_support import CREDS


class FakeObjectStore:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.clock = 1_000_000.0
        self.signed: list[tuple[str, str]] = []
        self.fail_puts = False
        store = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args) -> None:
                return

            def _key(self) -> str | None:
                parsed = urlsplit(self.path)
                expires = float(parse_qs(parsed.query)["expires"][0])
                if expires < store.clock:
                    self.send_response(403)
                    self.end_headers()
                    return None
                return parsed.path.lstrip("/")

            def do_PUT(self) -> None:  # noqa: N802 - http.server API
                key = self._key()
                if key is None:
                    return
                body = self.rfile.read(int(self.headers["Content-Length"]))
                if store.fail_puts:
                    self.send_response(500)
                    self.end_headers()
                    return
                store.objects[key] = (body, self.headers["Content-Type"])
                self.send_response(200)
                self.end_headers()

            def do_GET(self) -> None:  # noqa: N802 - http.server API
                key = self._key()
                if key is None:
                    return
                if key not in store.objects:
                    self.send_response(404)
                    self.end_headers()
                    return
                body, content_type = store.objects[key]
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)

    def sign(self, *, method: str, bucket: str, key: str, expires_s: int, **_kw) -> str:
        self.signed.append((method, key))
        port = self.server.server_address[1]
        return f"http://127.0.0.1:{port}/{key}?expires={self.clock + expires_s}"

    def advance(self, seconds: float) -> None:
        self.clock += seconds


@contextmanager
def fake_object_store() -> Iterator[FakeObjectStore]:
    """Serve a fake store and route the project credential signer to it."""
    store = FakeObjectStore()
    thread = threading.Thread(target=store.server.serve_forever, daemon=True)
    thread.start()
    try:
        with (
            patch("yoke_core.domain.s3_presign.presign_s3_url", side_effect=store.sign),
            patch(
                "yoke_core.domain.qa_artifact_configuration._capability_credentials",
                return_value=CREDS,
            ),
        ):
            yield store
    finally:
        store.server.shutdown()
        store.server.server_close()


__all__ = ["FakeObjectStore", "fake_object_store"]
