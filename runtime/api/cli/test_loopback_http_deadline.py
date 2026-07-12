"""Absolute open/header deadline for caller-owned loopback mutations."""

from __future__ import annotations

import socket
import threading
import time
import urllib.request

import pytest

from yoke_cli.transport import bounded_json_http as transport


def test_loopback_post_header_trickle_obeys_absolute_deadline() -> None:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    finished = threading.Event()

    def serve() -> None:
        try:
            connection, _address = listener.accept()
            with connection:
                connection.recv(64 * 1024)
                response = (
                    b"HTTP/1.1 200 OK\r\n"
                    b"Content-Type: application/json\r\n"
                    b"Content-Length: 2\r\n\r\n{}"
                )
                for byte in response:
                    try:
                        connection.sendall(bytes((byte,)))
                    except OSError:
                        break
                    time.sleep(0.02)
        finally:
            listener.close()
            finished.set()

    threading.Thread(target=serve, daemon=True).start()
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/health",
        data=b"{}",
        method="POST",
    )
    started = time.monotonic()
    with pytest.raises(transport.BoundedJsonHttpDeadlineError):
        transport.request_json(
            request,
            timeout_seconds=0.08,
            replay_safe=False,
            allow_loopback_http=True,
        )

    assert time.monotonic() - started < 0.5
    assert finished.wait(1.0)
