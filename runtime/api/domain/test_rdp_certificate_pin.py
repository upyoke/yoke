"""A direct RDP host's self-signed certificate is pinned on first use."""

from __future__ import annotations

import datetime
import hashlib
import socket
import ssl
import threading

import pytest

from yoke_harness import rdp_certificate_pin as pin

pytestmark = pytest.mark.windows

# X.224 Connection Confirm selecting PROTOCOL_SSL (RDP_NEG_RSP, protocol 1).
CONFIRM = bytes.fromhex("030000130ed00000123400020008000100000000")[:19]


class Refused(RuntimeError):
    pass


def _certificate(tmp_path, name):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = datetime.datetime.now(datetime.timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    cert_path = tmp_path / f"{name}.pem"
    key_path = tmp_path / f"{name}.key"
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    fingerprint = hashlib.sha256(
        certificate.public_bytes(serialization.Encoding.DER)
    ).hexdigest()
    return cert_path, key_path, fingerprint


def _serve(listener, cert_path, key_path, confirm=CONFIRM):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)

    def run():
        connection, _ = listener.accept()
        with connection:
            connection.recv(19)
            connection.sendall(confirm)
            if confirm[11:12] == b"\x03":
                return
            try:
                with context.wrap_socket(connection, server_side=True) as tls:
                    tls.recv(1)
            except (OSError, ssl.SSLError):
                pass

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


@pytest.fixture
def listener():
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        yield server


def _pinned(listener, tmp_path, name, home):
    cert_path, key_path, fingerprint = _certificate(tmp_path, name)
    thread = _serve(listener, cert_path, key_path)
    port = listener.getsockname()[1]
    try:
        return pin.pinned_certificate("127.0.0.1", port, Refused, yoke_home=home), fingerprint
    finally:
        thread.join(timeout=5)


def test_first_use_pins_and_the_same_certificate_is_accepted(listener, tmp_path, capsys):
    home = tmp_path / "home"
    cert_path, key_path, fingerprint = _certificate(tmp_path, "lab")
    port = listener.getsockname()[1]
    for _ in range(2):
        thread = _serve(listener, cert_path, key_path)
        assert pin.pinned_certificate("127.0.0.1", port, Refused, yoke_home=home) == fingerprint
        thread.join(timeout=5)
    pins = pin.pins_path(home)
    assert pins.read_text() == f"127.0.0.1:{port} {fingerprint}\n"
    assert capsys.readouterr().err.count("desktop_certificate_pinned") == 1


def test_a_changed_certificate_refuses_and_names_the_pin_to_delete(listener, tmp_path):
    home = tmp_path / "home"
    first, _ = _pinned(listener, tmp_path, "lab", home)
    with pytest.raises(Refused, match="desktop_certificate_changed") as refused:
        _pinned(listener, tmp_path, "impostor", home)
    port = listener.getsockname()[1]
    assert f"pinned sha256:{first}" in str(refused.value)
    assert f"delete the 127.0.0.1:{port} line from {pin.pins_path(home)}" in str(refused.value)
    assert pin.pins_path(home).read_text() == f"127.0.0.1:{port} {first}\n"


def test_a_host_without_tls_refuses_by_name(listener, tmp_path):
    cert_path, key_path, _ = _certificate(tmp_path, "lab")
    failure = CONFIRM[:11] + b"\x03" + CONFIRM[12:]
    thread = _serve(listener, cert_path, key_path, confirm=failure)
    with pytest.raises(Refused, match="desktop_certificate_unavailable"):
        pin.pinned_certificate(
            "127.0.0.1", listener.getsockname()[1], Refused, yoke_home=tmp_path / "home"
        )
    thread.join(timeout=5)
    assert not pin.pins_path(tmp_path / "home").exists()
