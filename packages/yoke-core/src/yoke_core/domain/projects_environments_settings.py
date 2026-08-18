"""Environment-settings surface: read/CAS-replace/merge ``environments.settings``.

``environments.settings`` is the DB authority
for per-environment deploy configuration (hosts, pulumi activation_state,
servers); this family is its sanctioned operator read/write surface.

Writes are lost-update protected via value-CAS (the as-read settings text
is the base token — :mod:`yoke_core.domain.settings_cas`): the full
replace requires ``--base`` and refuses with a typed
:class:`~yoke_core.domain.settings_cas.SettingsConflictError` when the
row moved; registered merge operations update single key paths through an
internal read-merge-CAS cycle so concurrent writers compose.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from yoke_core.domain.db_helpers import connect, query_one
from yoke_core.domain.settings_cas import (
    EMPTY_SETTINGS_DOC,
    SettingsConflictError,
    base_required_teaching,
    cas_merge_loop,
    parse_settings_object,
    settings_conflict_teaching,
)


_GET_RECIPE = (
    "yoke projects environment-settings get --project PROJECT "
    "--environment NAME --path key.path"
)
_MERGE_RECIPE = (
    "yoke projects environment-settings merge --project PROJECT "
    "--environment NAME --set key.path=value"
)


def _read_settings_text(conn: Any, environment_id: int) -> Optional[str]:
    """Return the as-read settings text for one row, or None when absent."""
    row = query_one(
        conn,
        "SELECT COALESCE(settings, '{}') AS settings "
        "FROM environments WHERE id=%s",
        (environment_id,),
    )
    if row is None:
        return None
    return str(row["settings"]) or EMPTY_SETTINGS_DOC


def _not_found(environment_id: int) -> LookupError:
    del environment_id
    return LookupError("Error: environment not found")


def cmd_environment_get_settings(
    environment_id: int,
    db_path: Optional[str] = None,
) -> str:
    """Return the settings JSON for one ``environments`` row, loudly.

    The returned text doubles as the CAS base token for
    :func:`cmd_environment_set_settings`.
    """
    conn = connect(db_path)
    try:
        text = _read_settings_text(conn, environment_id)
        if text is None:
            raise _not_found(environment_id)
        return text
    finally:
        conn.close()


def _cas_replace(
    conn: Any, environment_id: int, new_text: str, base_text: str
) -> str:
    """CAS-write one row; commit on success, typed refusal otherwise."""
    cur = conn.execute(
        "UPDATE environments SET settings=%s "
        "WHERE id=%s AND COALESCE(settings, '{}')=%s",
        (new_text, environment_id, base_text),
    )
    if cur.rowcount == 0:
        missing = _read_settings_text(conn, environment_id) is None
        conn.rollback()
        if missing:
            raise _not_found(environment_id)
        raise SettingsConflictError(
            settings_conflict_teaching(
                what="environment settings",
                get_recipe=_GET_RECIPE,
                merge_recipe=_MERGE_RECIPE,
            )
        )
    conn.commit()
    return "Set environment settings"


def cmd_environment_set_settings(
    environment_id: int,
    settings_json: str,
    base_settings_json: Optional[str] = None,
    db_path: Optional[str] = None,
) -> str:
    """Validate and CAS-replace settings for one ``environments`` row.

    ``base_settings_json`` is the exact text the caller read via
    :func:`cmd_environment_get_settings`; the write lands only while the
    stored text still equals it (value-CAS lost-update protection; no
    blind-replace path exists).
    """
    if base_settings_json is None or not str(base_settings_json).strip():
        raise ValueError(
            base_required_teaching(
                get_recipe=_GET_RECIPE, merge_recipe=_MERGE_RECIPE
            )
        )
    parse_settings_object(settings_json, what="settings JSON")
    conn = connect(db_path)
    try:
        return _cas_replace(
            conn, environment_id, settings_json, base_settings_json
        )
    finally:
        conn.close()


def cmd_environment_merge_settings(
    environment_id: int,
    assignments: Dict[str, Any],
    db_path: Optional[str] = None,
) -> str:
    """Merge dot-path assignments into one row's settings (CAS, one retry)."""
    conn = connect(db_path)
    try:
        def read_current() -> Optional[str]:
            text = _read_settings_text(conn, environment_id)
            if text is None:
                raise _not_found(environment_id)
            return text

        def cas_write(base: Optional[str], merged_text: str) -> str:
            assert base is not None  # read_current raises on absent rows
            return _cas_replace(conn, environment_id, merged_text, base)

        cas_merge_loop(
            read_current=read_current,
            cas_write=cas_write,
            assignments=assignments,
            what="environment settings",
        )
        return (
            f"Merged {len(assignments)} key(s) into settings for "
            "environment"
        )
    finally:
        conn.close()
