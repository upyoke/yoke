"""Transactional migration of Pulumi operator state into its capability.

The values moved by this module contain Pulumi's encrypted data key.  They
must never cross the registered function boundary: callers receive only a
redacted receipt describing paths, stack names, verification, and mode.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Optional, Sequence

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import connect, iso8601_now
from yoke_core.domain.project_identity import resolve_project
from yoke_core.domain.projects_pulumi_state_migration_marker import (
    canonical_json as _canonical_json,
    destination_has_entries as _destination_has_exact_entries,
    marker_matches,
    remove_source_state as _remove_source_state,
    set_marker,
)

CAPABILITY_TYPE = "pulumi-state"
SOURCE_PATH = "sites.settings.pulumi.stack_state"
DESTINATION_PATH = "project_capabilities.settings.stack_state"
MARKER_PATH = "project_capabilities.settings.migration_receipts"
SENSITIVE_PATHS = (
    f"{SOURCE_PATH}.*.secrets_provider",
    f"{SOURCE_PATH}.*.encrypted_key",
    f"{DESTINATION_PATH}.*.secrets_provider",
    f"{DESTINATION_PATH}.*.encrypted_key",
)
_ENTRY_KEYS = frozenset({"secrets_provider", "encrypted_key"})

class PulumiStateMigrationError(RuntimeError):
    """Typed, secret-free refusal from the state migration workhorse."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code

def migrate_pulumi_state(
    *,
    project: str,
    site_id: str,
    stack_names: Sequence[str],
    apply: bool = False,
    db_path: Optional[str] = None,
    conn: Optional[Any] = None,
) -> dict[str, Any]:
    """Plan or apply one exact-set site-to-capability state migration."""
    requested = _normalize_stack_names(stack_names)
    owns_conn = conn is None
    if owns_conn:
        conn = connect(db_path)
    assert conn is not None
    try:
        ident = resolve_project(conn, project, required=False)
        if ident is None:
            raise PulumiStateMigrationError(
                "not_found", f"project {project!r} was not found"
            )
        site_row = _locked_site_row(conn, site_id)
        if site_row is None:
            raise PulumiStateMigrationError(
                "not_found", f"site {site_id!r} was not found"
            )
        if int(site_row[0]) != ident.id:
            raise PulumiStateMigrationError(
                "project_mismatch",
                f"site {site_id!r} does not belong to project {ident.slug!r}",
            )

        capability_created = _ensure_capability_row(conn, ident.id)
        capability_row = _locked_capability_row(conn, ident.id)
        assert capability_row is not None
        site_settings = _object_from_json(site_row[1], SOURCE_PATH)
        capability_settings = _object_from_json(
            capability_row[0], DESTINATION_PATH
        )

        source_state = _source_stack_state(site_settings)
        destination_state = _destination_stack_state(capability_settings)
        source_entries = _validated_entries(source_state, SOURCE_PATH)
        destination_entries = _validated_entries(
            destination_state, DESTINATION_PATH, selected=requested
        )

        if source_entries is None:
            if (
                marker_matches(capability_settings, site_id, requested)
                and _destination_has_exact_entries(destination_entries, requested)
            ):
                mode = "already_applied"
                changed_paths: list[str] = []
            else:
                raise PulumiStateMigrationError(
                    "not_found",
                    "no Pulumi stack state exists at the requested source path",
                )
        else:
            source_names = frozenset(source_entries)
            if source_names != frozenset(requested):
                raise PulumiStateMigrationError(
                    "stack_set_mismatch",
                    "requested stack names must exactly match the source stack set",
                )
            conflicts = [
                name
                for name in requested
                if name in destination_entries
                and destination_entries[name] != source_entries[name]
            ]
            if conflicts:
                raise PulumiStateMigrationError(
                    "stack_state_conflict",
                    "destination Pulumi state conflicts for stack(s): "
                    + ", ".join(sorted(conflicts)),
                )
            source_cleanup_only = all(
                destination_entries.get(name) == source_entries[name]
                for name in requested
            )
            mode = "source_cleanup_only" if source_cleanup_only else "migrate"
            changed_paths = [SOURCE_PATH]
            if not source_cleanup_only:
                changed_paths.insert(0, DESTINATION_PATH)

            merged_destination = dict(destination_state)
            merged_destination.update(source_entries)
            capability_settings["stack_state"] = merged_destination
            set_marker(capability_settings, site_id, requested)
            if MARKER_PATH not in changed_paths:
                changed_paths.append(MARKER_PATH)
            _remove_source_state(site_settings)
            conn.execute(
                "UPDATE project_capabilities SET settings=%s "
                "WHERE project_id=%s AND type=%s",
                (_canonical_json(capability_settings), ident.id, CAPABILITY_TYPE),
            )
            conn.execute(
                "UPDATE sites SET settings=%s WHERE id=%s",
                (_canonical_json(site_settings), site_id),
            )

        if capability_created and mode == "already_applied":
            # An insert-only empty row cannot prove already-applied state.
            raise PulumiStateMigrationError(
                "not_found",
                "no Pulumi stack state exists at the requested source path",
            )

        if apply:
            _verify_applied(conn, ident.id, site_id, requested)
            conn.commit()
            applied = True
        else:
            conn.rollback()
            applied = False

        receipt = {
            "project": ident.slug,
            "site_id": str(site_id),
            "capability_type": CAPABILITY_TYPE,
            "mode": mode,
            "stack_names": list(requested),
            "source_path": SOURCE_PATH,
            "destination_path": DESTINATION_PATH,
            "changed_paths": changed_paths,
            "source_stack_set_verified": True,
            "destination_verified": True,
            "source_removed": mode == "already_applied" or bool(apply),
            "sensitive_paths": list(SENSITIVE_PATHS),
            "applied": applied,
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

def _normalize_stack_names(stack_names: Sequence[str]) -> tuple[str, ...]:
    names = tuple(str(name or "").strip() for name in stack_names)
    if not names or any(not name for name in names):
        raise PulumiStateMigrationError(
            "validation_error", "at least one non-empty stack name is required"
        )
    if len(names) != len(set(names)):
        raise PulumiStateMigrationError(
            "validation_error", "stack names must be unique"
        )
    return tuple(sorted(names))

def _locked_site_row(conn: Any, site_id: str) -> Any:
    suffix = " FOR UPDATE" if db_backend.connection_is_postgres(conn) else ""
    return conn.execute(
        "SELECT project_id, COALESCE(settings, '{}') FROM sites "
        f"WHERE id=%s{suffix}",
        (site_id,),
    ).fetchone()


def _ensure_capability_row(conn: Any, project_id: int) -> bool:
    cursor = conn.execute(
        "INSERT INTO project_capabilities "
        "(project_id, type, settings, created_at) VALUES (%s, %s, %s, %s) "
        "ON CONFLICT(project_id, type) DO NOTHING",
        (project_id, CAPABILITY_TYPE, "{}", iso8601_now()),
    )
    return cursor.rowcount == 1


def _locked_capability_row(conn: Any, project_id: int) -> Any:
    suffix = " FOR UPDATE" if db_backend.connection_is_postgres(conn) else ""
    return conn.execute(
        "SELECT COALESCE(settings, '{}') FROM project_capabilities "
        f"WHERE project_id=%s AND type=%s{suffix}",
        (project_id, CAPABILITY_TYPE),
    ).fetchone()


def _object_from_json(raw: Any, path: str) -> dict[str, Any]:
    if isinstance(raw, Mapping):
        value: Any = dict(raw)
    else:
        try:
            value = json.loads(str(raw or "{}"))
        except (TypeError, json.JSONDecodeError) as exc:
            raise PulumiStateMigrationError(
                "validation_error", f"stored JSON at {path} is invalid"
            ) from exc
    if not isinstance(value, dict):
        raise PulumiStateMigrationError(
            "validation_error", f"stored JSON at {path} must be an object"
        )
    return value


def _source_stack_state(settings: Mapping[str, Any]) -> Any:
    pulumi = settings.get("pulumi")
    if pulumi is None:
        return None
    if not isinstance(pulumi, Mapping):
        raise PulumiStateMigrationError(
            "validation_error", "sites.settings.pulumi must be an object"
        )
    return pulumi.get("stack_state")


def _destination_stack_state(settings: Mapping[str, Any]) -> dict[str, Any]:
    raw = settings.get("stack_state")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise PulumiStateMigrationError(
            "validation_error", f"{DESTINATION_PATH} must be an object"
        )
    return dict(raw)


def _validated_entries(
    state: Any,
    path: str,
    *,
    selected: Sequence[str] | None = None,
) -> Optional[dict[str, dict[str, str]]]:
    if state is None:
        return None
    if not isinstance(state, Mapping):
        raise PulumiStateMigrationError(
            "validation_error", f"{path} must be an object"
        )
    names = set(selected) if selected is not None else set(state)
    result: dict[str, dict[str, str]] = {}
    for name in sorted(names & set(state)):
        raw_entry = state[name]
        if not isinstance(raw_entry, Mapping):
            raise PulumiStateMigrationError(
                "validation_error", f"{path} entries must be objects"
            )
        if set(raw_entry) != _ENTRY_KEYS:
            raise PulumiStateMigrationError(
                "validation_error",
                f"{path} entries must contain only secrets_provider and encrypted_key",
            )
        canonical: dict[str, str] = {}
        for key in sorted(_ENTRY_KEYS):
            value = raw_entry[key]
            if isinstance(value, (dict, list)) or value is None:
                raise PulumiStateMigrationError(
                    "validation_error", f"{path} entry values must be non-empty scalars"
                )
            text = str(value).strip()
            if not text:
                raise PulumiStateMigrationError(
                    "validation_error", f"{path} entry values must be non-empty scalars"
                )
            canonical[key] = text
        result[str(name)] = canonical
    return result


def _verify_applied(
    conn: Any, project_id: int, site_id: str, requested: Sequence[str]
) -> None:
    site_row = conn.execute(
        "SELECT COALESCE(settings, '{}') FROM sites WHERE id=%s", (site_id,)
    ).fetchone()
    capability_row = conn.execute(
        "SELECT COALESCE(settings, '{}') FROM project_capabilities "
        "WHERE project_id=%s AND type=%s",
        (project_id, CAPABILITY_TYPE),
    ).fetchone()
    if site_row is None or capability_row is None:
        raise PulumiStateMigrationError(
            "verification_failed", "Pulumi state migration verification failed"
        )
    source = _source_stack_state(_object_from_json(site_row[0], SOURCE_PATH))
    destination = _destination_stack_state(
        _object_from_json(capability_row[0], DESTINATION_PATH)
    )
    validated = _validated_entries(
        destination, DESTINATION_PATH, selected=requested
    )
    settings = _object_from_json(capability_row[0], DESTINATION_PATH)
    if (
        source is not None
        or not _destination_has_exact_entries(validated, requested)
        or not marker_matches(settings, site_id, requested)
    ):
        raise PulumiStateMigrationError(
            "verification_failed", "Pulumi state migration verification failed"
        )

__all__ = [
    "CAPABILITY_TYPE",
    "DESTINATION_PATH",
    "MARKER_PATH",
    "PulumiStateMigrationError",
    "SENSITIVE_PATHS",
    "SOURCE_PATH",
    "migrate_pulumi_state",
]
