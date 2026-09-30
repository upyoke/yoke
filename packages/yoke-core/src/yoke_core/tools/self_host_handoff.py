"""Docker-exec stdin bridge to the bootstrap's private Unix socket.

Exec stdout belongs to the host process, not the container log driver. The
server keeps this socket across its privilege drop and exec for token delivery.
"""

from __future__ import annotations

import base64
from yoke_core.domain.json_helper import dumps_compact, loads_text
import os
import select
import socket
import sys
import time
import threading
import urllib.request

from yoke_contracts.self_host_handoff import (
    HANDOFF_ACK,
    HANDOFF_MAX_BYTES,
    HANDOFF_SOCKET,
    HANDOFF_TIMEOUT_SECONDS,
)
from yoke_contracts.self_host_bootstrap_output import FIRST_BOOT_TOKEN_FD_ENV
from yoke_core.tools.self_host_secret_materialization import (
    SelfHostServerBootstrapError,
)


def receive_bootstrap_handoff(
    env: dict[str, str],
) -> tuple[dict[str, str], dict[str, bytes]]:
    """Accept a single bounded host input while still container root."""
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection = None
    try:
        listener.bind(HANDOFF_SOCKET)
        os.chmod(HANDOFF_SOCKET, 0o600)
        listener.listen(1)
        listener.settimeout(HANDOFF_TIMEOUT_SECONDS)
        connection, _ = listener.accept()
        connection.settimeout(HANDOFF_TIMEOUT_SECONDS)
        wire = bytearray()
        while not wire.endswith(b"\n"):
            chunk = connection.recv(1)
            if not chunk or len(wire) >= HANDOFF_MAX_BYTES:
                raise ValueError("handoff missing or oversized")
            wire.extend(chunk)
        payload = loads_text(wire.decode())
        payloads = {
            name: base64.b64decode(value, validate=True)
            for name, value in payload.items()
        }
        connection.settimeout(None)
        descriptor = connection.detach()
        os.set_inheritable(descriptor, True)
        return {**env, FIRST_BOOT_TOKEN_FD_ENV: str(descriptor)}, payloads
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        raise SelfHostServerBootstrapError(
            "self_host_handoff_failed: host input did not arrive safely; "
            "use `yoke self-host init --dir <bundle> --protect-existing --start`"
        ) from exc
    finally:
        listener.close()
        if connection is not None:
            connection.close()
        try:
            os.unlink(HANDOFF_SOCKET)
        except FileNotFoundError:
            pass


def _health_ready() -> bool:
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:8765/v1/health", timeout=1
        ) as reply:
            return reply.status == 200
    except OSError:
        return False


def _stream_import(connection: socket.socket) -> int:
    """Relay the archive/result without putting either in Docker logs."""

    def send():
        try:
            while chunk := sys.stdin.buffer.read(65536):
                connection.sendall(chunk)
            connection.shutdown(socket.SHUT_WR)
        except OSError:
            connection.close()

    connection.settimeout(HANDOFF_TIMEOUT_SECONDS)
    sender = threading.Thread(target=send, daemon=True)
    sender.start()
    while chunk := connection.recv(65536):
        sys.stdout.buffer.write(chunk)
    sys.stdout.buffer.flush()
    sender.join(timeout=HANDOFF_TIMEOUT_SECONDS)
    return 0


def main() -> int:
    """Read secrets on stdin and return a token or healthy-restart receipt."""
    deadline = time.monotonic() + HANDOFF_TIMEOUT_SECONDS
    try:
        header = sys.stdin.buffer.readline(HANDOFF_MAX_BYTES + 1)
        if not header.endswith(b"\n") or len(header) > HANDOFF_MAX_BYTES:
            raise ValueError("handoff missing or oversized")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            while True:
                try:
                    connection.connect(HANDOFF_SOCKET)
                    break
                except (FileNotFoundError, ConnectionRefusedError):
                    if time.monotonic() >= deadline:
                        raise TimeoutError("bootstrap did not open its handoff")
                    time.sleep(0.1)
            connection.sendall(header)
            if sys.argv[1:] == ["--stream"]:
                return _stream_import(connection)
            connection.settimeout(HANDOFF_TIMEOUT_SECONDS)
            while time.monotonic() < deadline:
                if select.select([connection], [], [], 0.2)[0]:
                    token = bytearray()
                    while not token.endswith(b"\n") and len(token) < 256:
                        chunk = connection.recv(1)
                        if not chunk:
                            raise ValueError("bootstrap closed before token delivery")
                        token.extend(chunk)
                    print(dumps_compact({"token": token.decode().strip()}), flush=True)
                    if sys.stdin.buffer.readline(len(HANDOFF_ACK) + 1) != HANDOFF_ACK:
                        raise ValueError(
                            "host did not acknowledge durable token storage"
                        )
                    connection.sendall(HANDOFF_ACK)
                    return 0
                if _health_ready():
                    print(dumps_compact({"healthy": True}), flush=True)
                    return 0
            raise TimeoutError("bootstrap did not become healthy")
    except (OSError, ValueError, UnicodeError):
        print(
            "self_host_handoff_failed: bootstrap transport failed; inspect core logs "
            "and retry self-host init --protect-existing --start",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
