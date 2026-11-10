"""Drop one removed stack's Pulumi operator state from the capability.

The inverse of checkpoint registration: after ``pulumi stack rm`` succeeds,
the stack's ``stack_state`` entry would otherwise make stack init refuse that
name forever.  The entry is ciphertext metadata; it is never returned.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

from yoke_core.domain.db_helpers import connect
from yoke_core.domain.project_identity import resolve_project
from yoke_core.domain.projects_pulumi_state_checkpoint_import import (
    DESTINATION_PATH,
    PulumiCheckpointImportError,
    _locked_capability_row,
    _settings_object,
)
from yoke_core.domain.pulumi_state_capability import (
    CAPABILITY_TYPE,
    validate_json_string,
    validate_stack_state,
)


def remove_stack_state(
    *,
    project: str,
    stack_name: str,
    db_path: Optional[str] = None,
    conn: Optional[Any] = None,
) -> dict[str, Any]:
    """Remove one exact stack's operator-state entry and verify it is gone."""
    name = str(stack_name or "").strip()
    if not name:
        raise PulumiCheckpointImportError(
            "validation_error", "a non-empty stack name is required"
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
        registered = name in state
        if registered:
            del state[name]
            settings["stack_state"] = state
            canonical = validate_json_string(
                json.dumps(settings, sort_keys=True, separators=(",", ":"))
            )
            conn.execute(
                "UPDATE project_capabilities SET settings=%s "
                "WHERE project_id=%s AND type=%s",
                (canonical, ident.id, CAPABILITY_TYPE),
            )
            _verify_absent(conn, ident.id, name)
        conn.commit()
        receipt: dict[str, Any] = {
            "project": ident.slug,
            "capability_type": CAPABILITY_TYPE,
            "stack_name": name,
            "mode": "removed" if registered else "not_registered",
            "destination_path": DESTINATION_PATH,
            "changed_paths": [f"{DESTINATION_PATH}.{name}"] if registered else [],
        }
        receipt["receipt_digest"] = hashlib.sha256(
            json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return receipt
    except Exception:
        conn.rollback()
        raise
    finally:
        if owns_conn:
            conn.close()


def _verify_absent(conn: Any, project_id: int, name: str) -> None:
    row = _locked_capability_row(conn, project_id)
    state = validate_stack_state(
        _settings_object(row[0]).get("stack_state", {}) if row else {}
    )
    if row is None or name in state:
        raise PulumiCheckpointImportError(
            "verification_failed", "stack-state removal verification failed"
        )


__all__ = ["remove_stack_state"]
