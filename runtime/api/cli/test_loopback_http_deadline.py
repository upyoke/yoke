"""Absolute open/header deadline for caller-owned loopback mutations."""

from __future__ import annotations

import socket
import threading
import time
import urllib.request

import pytest

from yoke_contracts import bounded_json_http as transport


def test_loopback_post_header_trickle_obeys_absolute_deadline() -> None:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    listener.settimeout(0.1)
    port = listener.getsockname()[1]
    finished = threading.Event()
    stop = threading.Event()

    def serve() -> None:
        try:
            while not stop.is_set():
                try:
                    connection, _address = listener.accept()
                    break
                except TimeoutError:
                    continue
            else:
                return
            with connection:
                connection.settimeout(0.1)
                connection.recv(64 * 1024)
                response = (
                    b"HTTP/1.1 200 OK\r\n"
                    b"Content-Type: application/json\r\n"
                    b"Content-Length: 2\r\n\r\n{}"
                )
                for byte in response:
                    if stop.is_set():
                        break
                    try:
                        connection.sendall(bytes((byte,)))
                    except OSError:
                        break
                    stop.wait(0.02)
        except TimeoutError:
            pass
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
    try:
        with pytest.raises(transport.BoundedJsonHttpDeadlineError):
            transport.request_json(
                request,
                timeout_seconds=0.08,
                replay_safe=False,
                allow_private_http=True,
            )

        assert time.monotonic() - started < 0.5
    finally:
        stop.set()
        assert finished.wait(1.0)
