"""Typed registration of checkpoint-derived Pulumi operator state.

This boundary exists for an already-live stack whose encrypted data-key
metadata has no legacy site-settings source to migrate.  The ciphertext is
accepted over the authenticated function transport, validated, written only
to the closed ``pulumi-state`` capability, and never returned to the caller.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.project_identity import resolve_project
from yoke_core.domain.pulumi_state_capability import (
    CAPABILITY_TYPE,
    validate_json_string,
    validate_stack_state,
)


DESTINATION_PATH = "project_capabilities.settings.stack_state"
SENSITIVE_PATHS = (
    f"{DESTINATION_PATH}.*.secrets_provider",
    f"{DESTINATION_PATH}.*.encrypted_key",
)


class PulumiCheckpointImportError(RuntimeError):
    """Secret-free typed refusal from checkpoint registration."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def import_checkpoint_state(
    *,
    project: str,
    stack_name: str,
    secrets_provider: str,
    encrypted_key: str,
    apply: bool = False,
    db_path: Optional[str] = None,
    conn: Optional[Any] = None,
) -> dict[str, Any]:
    """Plan or register one exact checkpoint-derived stack entry."""
    name = str(stack_name or "").strip()
    if not name:
        raise PulumiCheckpointImportError(
            "validation_error", "a non-empty stack name is required"
        )
    try:
        entry = validate_stack_state(
            {
                name: {
                    "secrets_provider": secrets_provider,
                    "encrypted_key": encrypted_key,
                }
            }
        )[name]
    except ValueError as exc:
        raise PulumiCheckpointImportError("validation_error", str(exc)) from exc
    if not entry["secrets_provider"].startswith("awskms://"):
        raise PulumiCheckpointImportError(
            "validation_error",
            "checkpoint secrets_provider must use the awskms scheme",
        )

    owns_conn = conn is None
    if owns_conn:
        conn = connect(db_path)
    assert conn is not None
    try:
        ident = resolve_project(conn, project, required=False)
        if ident is None:
            raise PulumiCheckpointImportError(
                "not_found", f"project {project!r} was not found"
            )
        row = _locked_capability_row(conn, ident.id)
        if row is None:
            raise PulumiCheckpointImportError(
                "not_found",
                f"project {ident.slug!r} has no pulumi-state capability",
            )
        settings = _settings_object(row[0])
        try:
            state = validate_stack_state(settings.get("stack_state", {}))
        except ValueError as exc:
            raise PulumiCheckpointImportError(
                "validation_error", "stored Pulumi operator state is invalid"
            ) from exc
        existing = state.get(name)
        if existing is not None and existing != entry:
            raise PulumiCheckpointImportError(
                "stack_state_conflict",
                f"Pulumi operator state already differs for stack {name!r}",
            )

        mode = "already_registered" if existing == entry else "register"
        changed_paths = [] if existing == entry else [f"{DESTINATION_PATH}.{name}"]
        if existing is None:
            state[name] = entry
            settings["stack_state"] = state
            try:
                canonical_settings = validate_json_string(
                    json.dumps(settings, sort_keys=True, separators=(",", ":"))
                )
            except ValueError as exc:
                raise PulumiCheckpointImportError(
                    "validation_error", "merged Pulumi-state settings are invalid"
                ) from exc
            if apply:
                conn.execute(
                    "UPDATE project_capabilities SET settings=%s "
                    "WHERE project_id=%s AND type=%s",
                    (canonical_settings, ident.id, CAPABILITY_TYPE),
                )
                _verify_entry(conn, ident.id, name, entry)

        if apply:
            conn.commit()
        else:
            conn.rollback()

        receipt: dict[str, Any] = {
            "project": ident.slug,
            "capability_type": CAPABILITY_TYPE,
            "stack_name": name,
            "mode": mode,
            "destination_path": DESTINATION_PATH,
            "changed_paths": changed_paths,
            "destination_verified": bool(existing == entry or apply),
            "sensitive_paths": list(SENSITIVE_PATHS),
            "applied": bool(apply),
            "entry_digest": _entry_digest(entry),
        }
        receipt["receipt_digest"] = hashlib.sha256(
            _canonical_json(receipt).encode("utf-8")
        ).hexdigest()
        return receipt
    except Exception:
        conn.rollback()
        raise
    finally:
        if owns_conn:
            conn.close()


def _locked_capability_row(conn: Any, project_id: int) -> Any:
    suffix = " FOR UPDATE" if db_backend.connection_is_postgres(conn) else ""
    return conn.execute(
        "SELECT COALESCE(settings, '{}') FROM project_capabilities "
        f"WHERE project_id=%s AND type=%s{suffix}",
        (project_id, CAPABILITY_TYPE),
    ).fetchone()


def _settings_object(raw: Any) -> dict[str, Any]:
    if isinstance(raw, Mapping):
        value: Any = dict(raw)
    else:
        try:
            value = json.loads(str(raw or "{}"))
        except (TypeError, json.JSONDecodeError) as exc:
            raise PulumiCheckpointImportError(
                "validation_error", "stored Pulumi-state settings are invalid"
            ) from exc
    if not isinstance(value, dict):
        raise PulumiCheckpointImportError(
            "validation_error", "stored Pulumi-state settings must be an object"
        )
    return value


def _verify_entry(
    conn: Any, project_id: int, name: str, expected: Mapping[str, str]
) -> None:
    row = _locked_capability_row(conn, project_id)
    if row is None:
        raise PulumiCheckpointImportError(
            "verification_failed", "checkpoint registration verification failed"
        )
    settings = _settings_object(row[0])
    try:
        state = validate_stack_state(settings.get("stack_state", {}))
    except ValueError as exc:
        raise PulumiCheckpointImportError(
            "verification_failed", "checkpoint registration verification failed"
        ) from exc
    if state.get(name) != dict(expected):
        raise PulumiCheckpointImportError(
            "verification_failed", "checkpoint registration verification failed"
        )


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _entry_digest(entry: Mapping[str, str]) -> str:
    return hashlib.sha256(_canonical_json(dict(entry)).encode("utf-8")).hexdigest()


__all__ = [
    "DESTINATION_PATH",
    "PulumiCheckpointImportError",
    "SENSITIVE_PATHS",
    "import_checkpoint_state",
]
