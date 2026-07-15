"""Owner-only credential bundle for an attended source-authority cutoff."""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from psycopg import conninfo

from yoke_core.domain import source_authority_credential_file as credential_file
from yoke_core.domain.source_authority_credential_file import SourceCredentialError


BUNDLE_SCHEMA = "yoke.source-cutover-credential/v1"


@dataclass(frozen=True, repr=False)
class SourceCredentialBundle:
    path: Path
    database: str
    database_oid: int
    admin_role: str
    service_stop_receipt: str
    source_fingerprint: str
    original_dsn: str
    cutover_dsn: str
    original_rolcanlogin: bool
    retirement_receipt: str | None
    retired_at: str | None
    retirement_phase: str | None


def prepare_or_load(
    path: str | Path, *, original_dsn: str, database: str, database_oid: int,
    admin_role: str, service_stop_receipt: str, original_rolcanlogin: bool,
) -> SourceCredentialBundle:
    """Create once before commit, or reuse the same precommit crash artifact."""
    selected = credential_file.selected_path(path)
    if selected.exists() or selected.is_symlink():
        return _load_expected(
            selected, original_dsn=original_dsn, database=database,
            database_oid=database_oid, admin_role=admin_role,
            service_stop_receipt=service_stop_receipt,
            original_rolcanlogin=original_rolcanlogin,
        )
    original = conninfo.conninfo_to_dict(original_dsn)
    original_password = str(original.get("password") or "")
    if not original_password:
        raise SourceCredentialError(
            "source cutover requires a password-bearing Postgres authority"
        )
    if str(original.get("user") or "") != admin_role:
        raise SourceCredentialError(
            "source credential user does not match the database administrator"
        )
    replacement = secrets.token_urlsafe(48)
    cutover_dsn = conninfo.make_conninfo(**{**original, "password": replacement})
    payload = {
        "schema": BUNDLE_SCHEMA,
        "binding": {
            "database": database,
            "database_oid": int(database_oid),
            "admin_role": admin_role,
            "service_stop_receipt": service_stop_receipt,
            "source_fingerprint": source_fingerprint(original_dsn),
            "original_rolcanlogin": bool(original_rolcanlogin),
        },
        "credentials": {
            "original_dsn": original_dsn,
            "cutover_dsn": cutover_dsn,
        },
    }
    if credential_file.write_atomic_owner_only(selected, payload):
        return _decode(selected, payload)
    return _load_expected(
        selected, original_dsn=original_dsn, database=database,
        database_oid=database_oid, admin_role=admin_role,
        service_stop_receipt=service_stop_receipt,
        original_rolcanlogin=original_rolcanlogin,
    )


def _load_expected(
    path: Path, *, original_dsn: str, database: str, database_oid: int,
    admin_role: str, service_stop_receipt: str, original_rolcanlogin: bool,
) -> SourceCredentialBundle:
    bundle = load_bound(
        path, original_dsn=original_dsn,
        service_stop_receipt=service_stop_receipt,
    )
    expected = (database, int(database_oid), admin_role, original_rolcanlogin)
    actual = (
        bundle.database, bundle.database_oid, bundle.admin_role,
        bundle.original_rolcanlogin,
    )
    if actual != expected:
        raise SourceCredentialError(
            "existing cutover credential belongs to another source authority"
        )
    return bundle


def load_bound(
    path: str | Path, *, original_dsn: str | None = None,
    service_stop_receipt: str | None = None,
) -> SourceCredentialBundle:
    """Load a safe bundle and bind it to the configured original authority."""
    selected = credential_file.selected_path(path)
    credential_file.require_owner_only_regular(selected)
    try:
        payload = json.loads(selected.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SourceCredentialError("cutover credential is unreadable") from exc
    bundle = _decode(selected, payload)
    if original_dsn is not None:
        if bundle.source_fingerprint != source_fingerprint(original_dsn):
            raise SourceCredentialError(
                "cutover credential source fingerprint does not match"
            )
        if bundle.original_dsn != original_dsn:
            raise SourceCredentialError(
                "cutover credential original authority does not match"
            )
    if (
        service_stop_receipt is not None
        and bundle.service_stop_receipt != service_stop_receipt
    ):
        raise SourceCredentialError(
            "cutover credential quiesce receipt does not match"
        )
    return bundle


def source_fingerprint(dsn: str) -> str:
    """Bind connection coordinates and the original secret without emitting it."""
    parsed = conninfo.conninfo_to_dict(dsn)
    canonical = json.dumps(
        parsed, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def password_from_dsn(dsn: str) -> str:
    password = str(conninfo.conninfo_to_dict(dsn).get("password") or "")
    if not password:
        raise SourceCredentialError("cutover credential has no password")
    return password


def prepare_retirement(
    bundle: SourceCredentialBundle, *, retirement_receipt: str, retired_at: str,
) -> SourceCredentialBundle:
    """Fsync an idempotent retirement intent before disabling both logins."""
    current = load_bound(bundle.path, original_dsn=bundle.original_dsn)
    if current.retirement_receipt is not None or current.retired_at is not None:
        if (
            current.retirement_receipt != retirement_receipt
            or not current.retired_at
        ):
            raise SourceCredentialError(
                "cutover credential contains another retirement intent"
            )
        return current
    if not retirement_receipt or not retired_at:
        raise SourceCredentialError("retirement intent is incomplete")
    payload = _payload(current)
    payload["retirement"] = {
        "retirement_receipt": retirement_receipt,
        "retired_at": retired_at,
        "phase": "intent",
    }
    credential_file.replace_atomic_owner_only(current.path, payload)
    return load_bound(current.path, original_dsn=current.original_dsn)


def mark_retirement_transaction_started(
    bundle: SourceCredentialBundle,
) -> SourceCredentialBundle:
    """Persist that the cutover credential validated before retirement SQL."""
    current = load_bound(bundle.path, original_dsn=bundle.original_dsn)
    if (
        not current.retirement_receipt
        or not current.retired_at
        or current.retirement_phase not in {"intent", "transaction_started"}
    ):
        raise SourceCredentialError("retirement intent is incomplete")
    if current.retirement_phase == "transaction_started":
        return current
    payload = _payload(current)
    payload["retirement"]["phase"] = "transaction_started"
    credential_file.replace_atomic_owner_only(current.path, payload)
    return load_bound(current.path, original_dsn=current.original_dsn)


def delete_bundle(bundle: SourceCredentialBundle) -> None:
    credential_file.delete_owner_only(bundle.path)


def _decode(path: Path, payload: Any) -> SourceCredentialBundle:
    try:
        if not isinstance(payload, dict) or payload.get("schema") != BUNDLE_SCHEMA:
            raise ValueError
        binding = payload["binding"]
        credentials = payload["credentials"]
        original_rolcanlogin = binding["original_rolcanlogin"]
        if not isinstance(original_rolcanlogin, bool):
            raise ValueError
        bundle = SourceCredentialBundle(
            path=path,
            database=str(binding["database"]),
            database_oid=int(binding["database_oid"]),
            admin_role=str(binding["admin_role"]),
            service_stop_receipt=str(binding["service_stop_receipt"]),
            source_fingerprint=str(binding["source_fingerprint"]),
            original_dsn=str(credentials["original_dsn"]),
            cutover_dsn=str(credentials["cutover_dsn"]),
            original_rolcanlogin=original_rolcanlogin,
            retirement_receipt=(
                str(payload["retirement"]["retirement_receipt"])
                if "retirement" in payload else None
            ),
            retired_at=(
                str(payload["retirement"]["retired_at"])
                if "retirement" in payload else None
            ),
            retirement_phase=(
                str(payload["retirement"]["phase"])
                if "retirement" in payload else None
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise SourceCredentialError("cutover credential schema is invalid") from exc
    original = conninfo.conninfo_to_dict(bundle.original_dsn)
    cutover = conninfo.conninfo_to_dict(bundle.cutover_dsn)
    if (
        not bundle.database
        or bundle.database_oid <= 0
        or not bundle.admin_role
        or not bundle.service_stop_receipt
        or ((bundle.retirement_receipt is None) != (bundle.retired_at is None))
        or ((bundle.retirement_receipt is None) != (bundle.retirement_phase is None))
        or (
            bundle.retirement_receipt is not None
            and (
                not bundle.retirement_receipt
                or not bundle.retired_at
                or bundle.retirement_phase not in {"intent", "transaction_started"}
            )
        )
        or len(bundle.source_fingerprint) != 64
        or any(
            character not in "0123456789abcdef"
            for character in bundle.source_fingerprint
        )
        or
        source_fingerprint(bundle.original_dsn) != bundle.source_fingerprint
        or {k: v for k, v in original.items() if k != "password"}
        != {k: v for k, v in cutover.items() if k != "password"}
        or str(original.get("user") or "") != bundle.admin_role
        or not str(original.get("password") or "")
        or not str(cutover.get("password") or "")
        or original.get("password") == cutover.get("password")
    ):
        raise SourceCredentialError("cutover credential binding is invalid")
    return bundle


def _payload(bundle: SourceCredentialBundle) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": BUNDLE_SCHEMA,
        "binding": {
            "database": bundle.database,
            "database_oid": bundle.database_oid,
            "admin_role": bundle.admin_role,
            "service_stop_receipt": bundle.service_stop_receipt,
            "source_fingerprint": bundle.source_fingerprint,
            "original_rolcanlogin": bundle.original_rolcanlogin,
        },
        "credentials": {
            "original_dsn": bundle.original_dsn,
            "cutover_dsn": bundle.cutover_dsn,
        },
    }
    if bundle.retirement_receipt is not None:
        payload["retirement"] = {
            "retirement_receipt": bundle.retirement_receipt,
            "retired_at": bundle.retired_at,
            "phase": bundle.retirement_phase,
        }
    return payload


__all__ = [
    "BUNDLE_SCHEMA", "SourceCredentialBundle", "SourceCredentialError",
    "delete_bundle", "load_bound", "mark_retirement_transaction_started",
    "password_from_dsn", "prepare_or_load", "prepare_retirement",
    "source_fingerprint",
]
