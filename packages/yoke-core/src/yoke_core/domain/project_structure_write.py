"""Write surface for the Project Structure aggregate.

Implements ``apply_patch`` and its op-shaped helpers per the constitution's
imperative op list contract: validate every op before applying any op, run
the whole batch in a single ``BEGIN IMMEDIATE`` transaction, and persist
the resulting Project Structure entries.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence, Tuple

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import (
    iso8601_now,
    query_one,
)
from yoke_core.domain.project_structure import (
    EMPTY_SLOT,
    NET_NEW_FAMILIES,
    UsageError,
    ValidationError,
    _connect,
)
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.project_structure_validation import (
    _require_known_family,
    _validate_envelope,
    _validate_payload,
)


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _normalize_op(op: Dict[str, Any]) -> Dict[str, Any]:
    """Return a normalized op dict with sentinel defaults.

    Does not validate envelope or payload — that happens inside the
    transaction.
    """
    if not isinstance(op, dict):
        raise UsageError(f"Each op must be a JSON object (got {type(op).__name__}).")
    op_name = op.get("op")
    if op_name not in ("put", "remove"):
        raise UsageError(
            f"Op verb must be 'put' or 'remove' (got {op_name!r})."
        )
    family = op.get("family")
    if not isinstance(family, str) or not family:
        raise UsageError("Each op must declare a non-empty 'family'.")
    attachment = op.get("attachment")
    if not isinstance(attachment, str) or not attachment:
        raise UsageError(
            f"Op on family '{family}' must declare a non-empty 'attachment'."
        )
    attachment_kind = op.get("attachment_kind") or EMPTY_SLOT
    if not isinstance(attachment_kind, str):
        raise UsageError(
            f"Op on family '{family}' attachment_kind must be a string."
        )
    entry_key = op.get("entry_key") or EMPTY_SLOT
    if not isinstance(entry_key, str):
        raise UsageError(
            f"Op on family '{family}' entry_key must be a string."
        )
    payload = op.get("payload")
    if op_name == "put" and payload is None:
        # Allow missing payload only for remove. Put demands explicit payload.
        raise UsageError(
            f"Put on family '{family}' must declare a 'payload' object."
        )
    return {
        "op": op_name,
        "family": family,
        "attachment_value": attachment,
        "attachment_kind": attachment_kind,
        "entry_key": entry_key,
        "payload": payload,
    }


def _derive_attachment_kind(family: str, attachment_kind: str) -> str:
    """Fill a locked family's attachment_kind when the caller omitted it.

    For a family locked to a single kind, callers may leave ``attachment_kind``
    empty in the op; the domain fills it in from the family envelope so
    downstream identity is complete.
    """
    env = NET_NEW_FAMILIES.get(family)
    if env is None:
        return attachment_kind
    branch = env["attachment"]
    locked = env["locked_kind"]
    if branch == "path_selector" and locked is not None and not attachment_kind:
        return locked
    return attachment_kind


def _apply_put(
    conn: Any,
    project_id: str,
    family: str,
    attachment_value: str,
    attachment_kind: str,
    entry_key: str,
    payload: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    p = _placeholder(conn)
    existing = query_one(
        conn,
        "SELECT payload, attachment_kind FROM project_structure "
        f"WHERE project_id={p} AND family={p} AND attachment_value={p} AND entry_key={p}",
        (project_id, family, attachment_value, entry_key),
    )
    before: Optional[Dict[str, Any]] = None
    payload_json = json.dumps(payload, sort_keys=True)
    now = iso8601_now()
    if existing is None:
        conn.execute(
            "INSERT INTO project_structure "
            "(project_id, family, attachment_value, attachment_kind, entry_key, "
            " payload, created_at, updated_at) "
            f"VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})",
            (project_id, family, attachment_value, attachment_kind, entry_key,
             payload_json, now, now),
        )
    else:
        try:
            before = json.loads(existing["payload"] or "{}")
        except (TypeError, ValueError):
            before = {}
        conn.execute(
            "UPDATE project_structure "
            f"SET attachment_kind={p}, payload={p}, "
            f"    updated_at={p} "
            f"WHERE project_id={p} AND family={p} AND attachment_value={p} AND entry_key={p}",
            (attachment_kind, payload_json, now, project_id, family, attachment_value, entry_key),
        )
    return before, payload


def _apply_remove(
    conn: Any,
    project_id: str,
    family: str,
    attachment_value: str,
    entry_key: str,
) -> Dict[str, Any]:
    p = _placeholder(conn)
    existing = query_one(
        conn,
        "SELECT payload FROM project_structure "
        f"WHERE project_id={p} AND family={p} AND attachment_value={p} AND entry_key={p}",
        (project_id, family, attachment_value, entry_key),
    )
    if existing is None:
        ident = _format_identity(project_id, family, attachment_value, entry_key)
        raise ValidationError(
            f"Cannot remove nonexistent entry: {ident}."
        )
    try:
        before = json.loads(existing["payload"] or "{}")
    except (TypeError, ValueError):
        before = {}
    conn.execute(
        "DELETE FROM project_structure "
        f"WHERE project_id={p} AND family={p} AND attachment_value={p} AND entry_key={p}",
        (project_id, family, attachment_value, entry_key),
    )
    return before


def _format_identity(
    project_id: str,
    family: str,
    attachment_value: str,
    entry_key: str,
) -> str:
    parts = [f"project={project_id}", f"family={family}", f"attachment={attachment_value}"]
    if entry_key:
        parts.append(f"entry_key={entry_key}")
    return "(" + ", ".join(parts) + ")"


def apply_patch(
    project_id: str,
    ops: Sequence[Dict[str, Any]],
    actor: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Apply an imperative op list atomically.

    Returns ``{"project_id", "applied_ops"}`` on success. Raises
    :class:`ValidationError` on envelope/payload mismatch and
    :class:`UsageError` on op-shape misuse.

    Single-request semantics:

    * Validates every op before applying any op.
    * Applies all ops in a single ``BEGIN IMMEDIATE`` transaction.
    """
    if not isinstance(ops, (list, tuple)) or len(ops) == 0:
        raise UsageError("ops must be a non-empty list.")

    normalized: List[Dict[str, Any]] = []
    for op in ops:
        norm = _normalize_op(op)
        _require_known_family(norm["family"])
        norm["attachment_kind"] = _derive_attachment_kind(
            norm["family"], norm["attachment_kind"]
        )
        _validate_envelope(
            norm["family"],
            norm["attachment_value"],
            norm["attachment_kind"],
            norm["entry_key"],
        )
        if norm["op"] == "put":
            norm["payload"] = _validate_payload(norm["family"], norm["payload"])
        normalized.append(norm)

    conn = _connect(db_path)
    try:
        numeric_project_id = resolve_project_id(conn, project_id)
        conn.execute("BEGIN" if db_backend.connection_is_postgres(conn) else "BEGIN IMMEDIATE")
        applied: List[Dict[str, Any]] = []
        for norm in normalized:
            if norm["op"] == "put":
                before, after = _apply_put(
                    conn,
                    str(numeric_project_id),
                    norm["family"],
                    norm["attachment_value"],
                    norm["attachment_kind"],
                    norm["entry_key"],
                    norm["payload"],
                )
                applied.append({**norm, "payload_before": before, "payload_after": after})
            else:
                before = _apply_remove(
                    conn,
                    str(numeric_project_id),
                    norm["family"],
                    norm["attachment_value"],
                    norm["entry_key"],
                )
                applied.append({**norm, "payload_before": before, "payload_after": None})

        conn.commit()
        return {
            "project_id": project_id,
            "applied_ops": [
                {
                    "op": e["op"],
                    "family": e["family"],
                    "attachment": e["attachment_value"],
                    "attachment_kind": e["attachment_kind"] or None,
                    "entry_key": e["entry_key"] or None,
                }
                for e in applied
            ],
        }
    except Exception:
        try:
            conn.rollback()
        except db_backend.database_error_types(conn):
            pass
        raise
    finally:
        conn.close()
