"""Proved machine identity: a signing key this host keeps, a public half it registers.

A machine id alone is an assertion. ``~/.yoke/config.json`` can be copied to a
second host, and both hosts then claim one relay identity: either box silently
takes the other's wakes and launches. The registry closes that by asking the
host to *prove* the id it claims — it signs a freshly stamped statement with a
private key that never leaves this machine, and the control plane checks the
signature against the public half recorded when the machine registered.

The key lives in its own file beside the machine config rather than inside it,
so the ordinary reasons a config gets copied (seeding a new box, sharing a
connection block) do not carry the secret along.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping

from yoke_contracts.machine_config.runtime import yoke_home


MACHINE_KEY_FILE_NAME = "machine-key.json"
KEY_ALGORITHM = "ed25519"
PROOF_VERSION = "v1"
# A proof is a statement about a moment. Accepting one forever would make a
# captured signature a permanent credential; accepting only the current second
# would fail every host whose clock drifts. Five minutes is the same window the
# rest of the fleet's liveness math already tolerates.
PROOF_MAX_SKEW_SECONDS = 300
_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class MachineIdentityError(RuntimeError):
    """The local key material is missing, unreadable, or malformed."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class MachineProofError(ValueError):
    """A presented proof does not establish the machine id it claims."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class MachineProof:
    """One signed statement that this host holds the named machine's key."""

    machine_id: str
    issued_at: str
    signature: str

    def as_payload(self) -> dict[str, str]:
        return {"issued_at": self.issued_at, "signature": self.signature}


def machine_key_path(home: str | Path | None = None) -> Path:
    """Return the machine-local key file path."""
    root = Path(home).expanduser() if home is not None else yoke_home()
    return root / MACHINE_KEY_FILE_NAME


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime(_TIMESTAMP_FORMAT)


def proof_material(machine_id: str, issued_at: str) -> bytes:
    """Return the exact bytes both sides sign and verify.

    Version-prefixed so a later proof shape cannot be replayed as this one.
    """
    return f"yoke-machine-proof:{PROOF_VERSION}:{machine_id}:{issued_at}".encode("utf-8")


def _signing_key(private_key: bytes) -> Any:
    from nacl.signing import SigningKey

    return SigningKey(private_key)


def _read_key_document(path: Path) -> dict[str, Any]:
    try:
        with path.open() as handle:
            payload = json.load(handle)
    except ValueError as exc:
        raise MachineIdentityError(
            "machine_key_unreadable",
            f"{path} is not valid JSON: {exc}. Recovery: delete it and re-run "
            "`yoke machine register --rotate-key` to mint and register a new key.",
        ) from exc
    if not isinstance(payload, dict):
        raise MachineIdentityError(
            "machine_key_unreadable",
            f"{path} must contain a JSON object. Recovery: delete it and re-run "
            "`yoke machine register --rotate-key`.",
        )
    return payload


def _decode(value: Any, *, field: str, path: Path) -> bytes:
    try:
        return base64.b64decode(str(value), validate=True)
    except (ValueError, TypeError) as exc:
        raise MachineIdentityError(
            "machine_key_unreadable",
            f"{path} has a malformed {field}. Recovery: delete it and re-run "
            "`yoke machine register --rotate-key`.",
        ) from exc


def _write_key_document(path: Path, document: Mapping[str, Any]) -> None:
    """Publish the key file atomically and owner-only."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    )
    temp_path = Path(handle.name)
    try:
        os.chmod(temp_path, 0o600)
        json.dump(dict(document), handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        os.replace(temp_path, path)
    finally:
        if not handle.closed:
            handle.close()
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass


def ensure_machine_keypair(
    home: str | Path | None = None,
    *,
    rotate: bool = False,
) -> str:
    """Create the machine key once and return its base64 public half.

    ``rotate=True`` mints a fresh pair, which is the recovery for a lost or
    compromised key — the new public half only takes effect once the machine
    re-registers it.
    """
    from nacl.signing import SigningKey

    path = machine_key_path(home)
    if path.is_file() and not rotate:
        document = _read_key_document(path)
        private = _decode(document.get("private_key"), field="private_key", path=path)
        return base64.b64encode(bytes(_signing_key(private).verify_key)).decode("ascii")
    signing_key = SigningKey.generate()
    public_key = base64.b64encode(bytes(signing_key.verify_key)).decode("ascii")
    _write_key_document(
        path,
        {
            "algorithm": KEY_ALGORITHM,
            "created_at": utc_now(),
            "private_key": base64.b64encode(bytes(signing_key)).decode("ascii"),
            "public_key": public_key,
        },
    )
    return public_key


def machine_public_key(home: str | Path | None = None) -> str | None:
    """Return the local public half, or ``None`` before a key exists."""
    path = machine_key_path(home)
    if not path.is_file():
        return None
    document = _read_key_document(path)
    private = _decode(document.get("private_key"), field="private_key", path=path)
    return base64.b64encode(bytes(_signing_key(private).verify_key)).decode("ascii")


def sign_machine_proof(
    machine_id: str,
    *,
    issued_at: str | None = None,
    home: str | Path | None = None,
) -> MachineProof:
    """Sign a freshly stamped claim to ``machine_id`` with the local key."""
    path = machine_key_path(home)
    if not path.is_file():
        raise MachineIdentityError(
            "machine_key_missing",
            f"no machine key at {path}. Recovery: run `yoke machine register` on "
            "this machine, which mints the key and registers its public half.",
        )
    document = _read_key_document(path)
    private = _decode(document.get("private_key"), field="private_key", path=path)
    stamped = issued_at or utc_now()
    signature = _signing_key(private).sign(proof_material(machine_id, stamped)).signature
    return MachineProof(
        machine_id=machine_id,
        issued_at=stamped,
        signature=base64.b64encode(signature).decode("ascii"),
    )


def _parse_timestamp(value: str, *, code: str) -> datetime:
    try:
        return datetime.strptime(value, _TIMESTAMP_FORMAT).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError) as exc:
        raise MachineProofError(
            code,
            f"proof timestamp {value!r} is not a canonical UTC timestamp "
            f"({_TIMESTAMP_FORMAT}).",
        ) from exc


def verify_machine_proof(
    *,
    public_key: str,
    machine_id: str,
    issued_at: str,
    signature: str,
    now: str,
    max_skew_seconds: int = PROOF_MAX_SKEW_SECONDS,
) -> None:
    """Raise :class:`MachineProofError` unless the proof holds for ``machine_id``.

    Freshness is checked before the signature so an expired proof reports the
    reason an operator can act on rather than a generic mismatch.
    """
    from nacl.exceptions import BadSignatureError, CryptoError
    from nacl.signing import VerifyKey

    stamped = _parse_timestamp(issued_at, code="machine_proof_invalid")
    current = _parse_timestamp(now, code="machine_proof_invalid")
    if abs(current - stamped) > timedelta(seconds=max_skew_seconds):
        raise MachineProofError(
            "machine_proof_expired",
            f"proof was issued at {issued_at}, outside the {max_skew_seconds}s "
            "freshness window. Recovery: correct this machine's clock, then "
            "restart the relay.",
        )
    try:
        VerifyKey(base64.b64decode(public_key, validate=True)).verify(
            proof_material(machine_id, issued_at),
            base64.b64decode(signature, validate=True),
        )
    except (BadSignatureError, CryptoError, ValueError, TypeError) as exc:
        raise MachineProofError(
            "machine_proof_invalid",
            f"proof does not match the key registered for machine {machine_id}. "
            "Recovery: run `yoke machine register --rotate-key` on the machine "
            "that owns this id, or clear the copied machine id on this host.",
        ) from exc


__all__ = [
    "KEY_ALGORITHM",
    "MACHINE_KEY_FILE_NAME",
    "MachineIdentityError",
    "MachineProof",
    "MachineProofError",
    "PROOF_MAX_SKEW_SECONDS",
    "PROOF_VERSION",
    "ensure_machine_keypair",
    "machine_key_path",
    "machine_public_key",
    "proof_material",
    "sign_machine_proof",
    "utc_now",
    "verify_machine_proof",
]
