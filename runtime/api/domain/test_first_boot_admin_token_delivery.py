"""Private token delivery requires the host's durable-storage acknowledgment."""

import socket
import threading

import pytest

from yoke_core.api import first_boot_admin_token_delivery as subject
from yoke_contracts.self_host_handoff import HANDOFF_ACK
from yoke_contracts.self_host_bootstrap_output import (
    API_PUBLISH_ENV,
    FIRST_BOOT_TOKEN_FD_ENV,
    FIRST_BOOT_TOKEN_HOST_PATH_ENV,
    FIRST_BOOT_TOKEN_MARKER,
    TOKEN_PREFIX,
    TOKEN_BODY_LENGTH,
)

RAW_TOKEN = TOKEN_PREFIX + "B" * TOKEN_BODY_LENGTH


def test_token_returns_over_private_socket_and_never_enters_logs(capsys):
    server, host = socket.socketpair()
    received = []

    def store():
        received.append(host.recv(256))
        host.sendall(HANDOFF_ACK)

    worker = threading.Thread(target=store)
    worker.start()
    try:
        banner = subject.deliver_first_boot_admin_token(
            RAW_TOKEN,
            env={
                FIRST_BOOT_TOKEN_FD_ENV: str(server.fileno()),
                FIRST_BOOT_TOKEN_HOST_PATH_ENV: "./secrets/first-boot-admin-token",
                API_PUBLISH_ENV: "0.0.0.0:9100",
            },
        )
    finally:
        worker.join(timeout=2)
        host.close()
        server.close()
    assert received == [(RAW_TOKEN + "\n").encode()]
    printed = capsys.readouterr().out
    assert RAW_TOKEN not in printed
    assert FIRST_BOOT_TOKEN_MARKER in banner
    assert "yoke connect http://127.0.0.1:9100 --token-stdin" in banner


def test_missing_handoff_refuses_without_printing_token(capsys):
    with pytest.raises(
        subject.FirstBootTokenDeliveryError, match="self_host_token_handoff_missing"
    ):
        subject.deliver_first_boot_admin_token(
            RAW_TOKEN, env={FIRST_BOOT_TOKEN_HOST_PATH_ENV: "./secrets/token"}
        )
    assert RAW_TOKEN not in capsys.readouterr().out


def test_closed_handoff_refuses_without_printing_token(capsys):
    server, host = socket.socketpair()
    host.close()
    try:
        with pytest.raises(
            subject.FirstBootTokenDeliveryError, match="self_host_token_handoff_failed"
        ):
            subject.deliver_first_boot_admin_token(
                RAW_TOKEN, env={FIRST_BOOT_TOKEN_FD_ENV: str(server.fileno())}
            )
    finally:
        server.close()
    assert RAW_TOKEN not in capsys.readouterr().out


def test_unacknowledged_storage_refuses(capsys):
    server, host = socket.socketpair()

    def refuse_storage():
        host.recv(256)
        host.shutdown(socket.SHUT_RDWR)

    worker = threading.Thread(target=refuse_storage)
    worker.start()
    try:
        with pytest.raises(
            subject.FirstBootTokenDeliveryError, match="self_host_token_handoff_failed"
        ):
            subject.deliver_first_boot_admin_token(
                RAW_TOKEN, env={FIRST_BOOT_TOKEN_FD_ENV: str(server.fileno())}
            )
    finally:
        worker.join(timeout=2)
        host.close()
        server.close()
    assert RAW_TOKEN not in capsys.readouterr().out


def test_server_outside_bundle_still_delivers_its_token(capsys):
    subject.deliver_first_boot_admin_token(
        RAW_TOKEN, env={API_PUBLISH_ENV: "127.0.0.1:8765"}
    )
    printed = capsys.readouterr().out
    assert RAW_TOKEN in printed
    assert "This log now holds the token" in printed
