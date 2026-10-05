"""The one item-identity resolver.

Callers name an item by its public reference: ``PREFIX-N``
(``projects.public_item_prefix`` + ``items.project_sequence``). A bare
``N`` names a project sequence, so it identifies an item only when the call
carries an explicit project; without one it is refused, and it is never
read as an internal ``items.id``. :func:`resolve_item_ref` turns either
accepted shape into the internal id the engine works with. Every surface
that accepts an item token from outside the engine — the dispatcher's
target and payload refs, CLI arguments, stored public refs — resolves
through it.

Internal ``items.id`` values stay inside the engine. The scheduler's own
item keys (an int or its digit string, or a stored public ref) normalize
through :func:`internal_item_key`, which is engine currency and never a
caller-input path.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Union

from yoke_contracts.public_ref import parse_public_item_ref

from . import db_backend

ITEM_REF_INVALID = "item_ref_invalid"
ITEM_REF_NEEDS_PROJECT = "item_ref_needs_project"
ITEM_REF_NOT_FOUND = "item_ref_not_found"

ProjectContext = Optional[Union[str, int]]


class ItemRefError(ValueError):
    """A caller's item token that names no single item, with the fix."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _invalid(token: Any) -> ItemRefError:
    return ItemRefError(
        ITEM_REF_INVALID,
        f"invalid item ref {token!r}: pass the public ref (PREFIX-N, for "
        "example YOK-123), or a bare number together with an explicit project",
    )


def _needs_project(sequence: int) -> ItemRefError:
    return ItemRefError(
        ITEM_REF_NEEDS_PROJECT,
        f"bare item number {sequence} names a project sequence but no project: "
        f"pass the public ref (PREFIX-{sequence}) or an explicit project "
        "(--project <slug>)",
    )


def _not_found(token: str, project: ProjectContext) -> ItemRefError:
    where = f" in project {project!r}" if project not in (None, "") else ""
    return ItemRefError(ITEM_REF_NOT_FOUND, f"item ref {token!r} not found{where}")


def _project_identity(conn: Any, prefix: Optional[str], project: ProjectContext):
    from yoke_core.domain.project_identity import (
        resolve_project,
        resolve_project_for_public_prefix,
    )

    try:
        if prefix is not None:
            return resolve_project_for_public_prefix(conn, prefix, required=True)
        return resolve_project(conn, project, required=True)
    except LookupError as exc:
        raise ItemRefError(ITEM_REF_NOT_FOUND, str(exc)) from exc


def check_item_ref_shape(
    token: Any,
    *,
    project: ProjectContext = None,
) -> tuple[Optional[str], int]:
    """Refuse a token no lookup could resolve, without touching a database.

    Returns ``(prefix, sequence)`` — ``prefix`` is ``None`` for a bare
    number, which is accepted only alongside ``project``. A client checks
    here before it opens a connection or relays.
    """
    if not isinstance(token, str):
        raise _invalid(token)
    prefix, sequence = parse_public_item_ref(token.strip())
    if sequence is None:
        raise _invalid(token)
    if prefix is None and project in (None, ""):
        raise _needs_project(sequence)
    return prefix, sequence


def resolve_item_ref(conn: Any, token: Any, *, project: ProjectContext = None) -> int:
    """Resolve a caller's item token to the internal ``items.id``.

    ``token`` is text: ``PREFIX-N`` resolves through its prefix wherever the
    call comes from; a bare ``N`` resolves as sequence ``N`` of ``project``
    and is refused without one. Anything else — including a Python int,
    which only engine code holds — is refused. Raises :class:`ItemRefError`
    whose message names the fix.
    """
    prefix, sequence = check_item_ref_shape(token, project=project)
    text = token.strip()
    ident = _project_identity(conn, prefix, project)
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        f"SELECT id FROM items WHERE project_id = {p} AND project_sequence = {p}",
        (ident.id, sequence),
    ).fetchone()
    if row is None:
        raise _not_found(text, project)
    from yoke_core.domain.project_identity import row_value

    return int(row_value(row, "id", 0))


def resolve_item_ref_or_none(
    conn: Any,
    token: Any,
    *,
    project: ProjectContext = None,
) -> Optional[int]:
    """:func:`resolve_item_ref` answering ``None`` where it would refuse.

    For gate and audit readers that skip an unresolvable ref rather than
    abort; a surface that answers a caller refuses with the error instead.
    """
    try:
        return resolve_item_ref(conn, token, project=project)
    except ItemRefError:
        return None


def internal_ids_for_refs(conn: Any, refs: Iterable[Any]) -> Dict[str, int]:
    """Bulk-map ``PREFIX-N`` refs to internal ids in one statement.

    Stored public refs (``item_dependencies`` rows, frontier keys) resolve
    here. Tokens that are not a full ``PREFIX-N``, and refs that name no
    item, are omitted.
    """
    wanted: Dict[str, tuple[str, int]] = {}
    for ref in refs:
        text = str(ref).strip()
        prefix, sequence = parse_public_item_ref(text)
        if prefix is not None and sequence is not None:
            wanted[text] = (prefix, sequence)
    if not wanted:
        return {}
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    pairs = sorted(set(wanted.values()))
    marks = ", ".join(p for _ in pairs)
    try:
        rows = conn.execute(
            "SELECT UPPER(p.public_item_prefix) AS prefix, "
            "i.project_sequence AS seq, i.id AS internal_id "
            "FROM items i JOIN projects p ON p.id = i.project_id "
            f"WHERE UPPER(p.public_item_prefix) IN ({marks}) "
            f"AND i.project_sequence IN ({marks})",
            (*[prefix for prefix, _ in pairs], *[seq for _, seq in pairs]),
        ).fetchall()
    except db_backend.operational_error_types(conn):
        if db_backend.connection_is_postgres(conn):
            conn.rollback()
        rows = []
    resolved: Dict[tuple[str, int], int] = {}
    for row in rows:
        record = (
            dict(row)
            if hasattr(row, "keys")
            else {
                "prefix": row[0],
                "seq": row[1],
                "internal_id": row[2],
            }
        )
        if record["seq"] is not None:
            resolved[(str(record["prefix"]), int(record["seq"]))] = int(
                record["internal_id"]
            )
    return {text: resolved[pair] for text, pair in wanted.items() if pair in resolved}


def remap_ref_keys_to_internal(
    conn: Any,
    mapping: Dict[str, Any],
) -> Dict[int, Any]:
    """Rekey a public-ref-keyed mapping by internal item id."""
    ref_ids = internal_ids_for_refs(conn, mapping.keys())
    return {ref_ids[ref]: value for ref, value in mapping.items() if ref in ref_ids}


def internal_item_key(conn: Any, key: Any) -> Optional[int]:
    """Normalize one of the scheduler's own item keys to ``items.id``.

    Scheduler steps, offers, and claim scopes carry an item as its internal
    id (an int, or its digit string once serialized) or as a stored public
    ref. This is engine currency, not caller input: a caller's token
    resolves through :func:`resolve_item_ref`, which never reads a number
    as an internal id.
    """
    if key is None or isinstance(key, bool):
        return None
    if isinstance(key, int):
        return key
    text = str(key).strip()
    if text.isdigit():
        return int(text)
    return internal_ids_for_refs(conn, [text]).get(text)


__all__ = [
    "ITEM_REF_INVALID",
    "ITEM_REF_NEEDS_PROJECT",
    "ITEM_REF_NOT_FOUND",
    "ItemRefError",
    "check_item_ref_shape",
    "internal_ids_for_refs",
    "internal_item_key",
    "remap_ref_keys_to_internal",
    "resolve_item_ref",
    "resolve_item_ref_or_none",
]
