"""Trust-on-first-use pins for the self-signed certificate of a direct RDP host.

A direct route reaches the host's own RDP listener over a private network such
as a tailnet, so no SSH host key vouches for it. The first connection records
the SHA-256 fingerprint of the certificate the host presents; every later
connection hands FreeRDP that fingerprint (``/cert:fingerprint:sha256:...``)
and refuses by name if the host presents a different certificate.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import socket
import ssl
import sys

from yoke_contracts.machine_config.directories import create_private_directory
from yoke_contracts.owner_private_path import write_owner_private
from yoke_harness.test_machine_remote_exec import KNOWN_HOSTS_DIR_NAME

PINS_FILE_NAME = "rdp_certificates"
# X.224 Connection Request asking for TLS or CredSSP (requestedProtocols=3).
_CONNECTION_REQUEST = bytes.fromhex("030000130ee000000000000100080003000000")
_TIMEOUT_SECONDS = 10


def pins_path(yoke_home: Path) -> Path:
    """Where this machine pins every direct RDP certificate it has accepted."""
    return yoke_home / KNOWN_HOSTS_DIR_NAME / PINS_FILE_NAME


def _read_exact(connection: socket.socket, size: int) -> bytes:
    data = b""
    while len(data) < size:
        chunk = connection.recv(size - len(data))
        if not chunk:
            raise OSError("RDP negotiation closed")
        data += chunk
    return data


def certificate_fingerprint(host: str, port: int) -> str:
    """Negotiate RDP security, open TLS and return the leaf certificate SHA-256."""
    with socket.create_connection((host, port), timeout=_TIMEOUT_SECONDS) as raw:
        raw.sendall(_CONNECTION_REQUEST)
        header = _read_exact(raw, 4)
        if header[:2] != b"\x03\x00":
            raise OSError("RDP negotiation unavailable")
        confirm = _read_exact(raw, int.from_bytes(header[2:], "big") - 4)
        # An RDP_NEG_FAILURE (type 3) means the host offers no TLS at all.
        if len(confirm) >= 8 and confirm[7] == 3:
            raise OSError("RDP host refused TLS")
        context = ssl.create_default_context()
        # The certificate is self-signed; the pin below is the trust decision.
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        with context.wrap_socket(raw, server_hostname=host) as tls:
            der = tls.getpeercert(binary_form=True)
    if not der:
        raise OSError("RDP host presented no certificate")
    return hashlib.sha256(der).hexdigest()


def _read_pins(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    pins = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if len(fields) == 2:
            pins[fields[0]] = fields[1]
    return pins


def pinned_certificate(host: str, port: int, error, *, yoke_home: Path) -> str:
    """Return the pinned SHA-256 fingerprint, recording the first certificate seen."""
    path = pins_path(yoke_home)
    authority = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
    try:
        presented = certificate_fingerprint(host, port)
    except (OSError, ssl.SSLError):
        raise error(
            f"desktop_certificate_unavailable: {authority} did not complete an RDP TLS "
            "handshake; check the desktop service and that this workstation reaches the "
            "host over its private network, then retry"
        ) from None
    pins = _read_pins(path)
    pinned = pins.get(authority)
    if pinned is None:
        create_private_directory(path.parent)
        pins[authority] = presented
        write_owner_private(
            path, "".join(f"{key} {value}\n" for key, value in sorted(pins.items()))
        )
        print(
            f"desktop_certificate_pinned: {authority} sha256:{presented} in {path}",
            file=sys.stderr,
            flush=True,
        )
    elif pinned != presented:
        raise error(
            f"desktop_certificate_changed: {authority} presented sha256:{presented}, "
            f"pinned sha256:{pinned}. If the host's RDP certificate was deliberately "
            f"regenerated, delete the {authority} line from {path} and retry; otherwise "
            "do not connect"
        )
    return presented
