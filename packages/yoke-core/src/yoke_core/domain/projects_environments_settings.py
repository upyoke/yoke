"""Environment-settings surface: read/CAS-replace/merge ``environments.settings``.

Owner: ``yoke_core.domain.projects`` (orchestration layer), mirroring
how :mod:`yoke_core.domain.projects_capabilities_settings` owns the
capability settings family. ``environments.settings`` is the DB authority
for per-environment deploy configuration (hosts, pulumi activation_state,
servers); this family is its sanctioned operator read/write surface.

Writes are lost-update protected via value-CAS (the as-read settings text
is the base token — :mod:`yoke_core.domain.settings_cas`): the full
replace requires ``--base`` and refuses with a typed
:class:`~yoke_core.domain.settings_cas.SettingsConflictError` when the
row moved; ``environment-merge-settings`` updates single key paths
through an internal read-merge-CAS cycle so concurrent writers compose
instead of erasing each other. The parent wires the parser and dispatch
hooks exported here.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from yoke_core.domain.db_helpers import connect, query_one
from yoke_core.domain.settings_cas import (
    EMPTY_SETTINGS_DOC,
    SettingsConflictError,
    base_required_teaching,
    cas_merge_loop,
    parse_set_assignments,
    parse_settings_object,
    settings_conflict_teaching,
)


ENVIRONMENT_SETTINGS_COMMANDS = (
    "environment-get-settings",
    "environment-set-settings",
    "environment-merge-settings",
)

_GET_RECIPE = (
    "python3 -m yoke_core.domain.projects environment-get-settings "
    "<environment-id>"
)
_MERGE_RECIPE = (
    "python3 -m yoke_core.domain.projects environment-merge-settings "
    "<environment-id> --set key.path=value"
)


def register_environment_settings_parsers(sub: Any) -> None:
    """Register the three subcommand parsers on the parent's subparser action."""
    p = sub.add_parser(
        "environment-get-settings",
        help=(
            "Get environments.settings JSON (the printed text is the CAS "
            "base token for environment-set-settings)"
        ),
        description=(
            "Print the settings document for one environments row. The "
            "exact printed text is the compare-and-swap base token for a "
            "full-document write: get -> edit -> environment-set-settings "
            "--base '<as-read-text>'. Single-key updates skip the cycle "
            "via environment-merge-settings."
        ),
    )
    p.add_argument("environment_id")
    p = sub.add_parser(
        "environment-set-settings",
        help=(
            "CAS-replace environments.settings JSON (requires --base, the "
            "as-read text from environment-get-settings)"
        ),
        description=(
            "Full-document replace, compare-and-swap protected: pass the "
            "exact text environment-get-settings printed as --base. A "
            "stale base refuses with settings_conflict instead of "
            "silently erasing the newer write. Prefer "
            "environment-merge-settings for single-key updates."
        ),
    )
    p.add_argument("environment_id")
    p.add_argument("settings_json")
    p.add_argument(
        "--base",
        dest="base_settings_json",
        default=None,
        metavar="AS_READ_JSON",
        help=(
            "The exact settings text read via environment-get-settings; "
            "the write lands only while the stored text still equals it."
        ),
    )
    p = sub.add_parser(
        "environment-merge-settings",
        help=(
            "Merge key.path=value assignments into environments.settings "
            "(read-merge-CAS with one retry; concurrent writers compose)"
        ),
        description=(
            "Set individual keys without replacing the whole document: "
            "reads the current settings, applies each --set key.path=value "
            "(value parsed as JSON when possible, raw string otherwise), "
            "and CAS-writes with one retry on conflict."
        ),
    )
    p.add_argument("environment_id")
    p.add_argument(
        "--set",
        dest="assignments",
        action="append",
        required=True,
        metavar="KEY.PATH=VALUE",
        help="Assignment to merge; repeatable.",
    )


def run_environment_settings_command(args: Any) -> int:
    """Dispatch one ENVIRONMENT_SETTINGS_COMMANDS member parsed by the parent."""
    if args.command == "environment-get-settings":
        print(cmd_environment_get_settings(args.environment_id))
    elif args.command == "environment-set-settings":
        print(
            cmd_environment_set_settings(
                args.environment_id,
                args.settings_json,
                args.base_settings_json,
            )
        )
    else:
        print(
            cmd_environment_merge_settings(
                args.environment_id,
                parse_set_assignments(args.assignments),
            )
        )
    return 0


def _read_settings_text(conn: Any, environment_id: str) -> Optional[str]:
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


def _not_found(environment_id: str) -> LookupError:
    return LookupError(f"Error: environment '{environment_id}' not found")


def cmd_environment_get_settings(
    environment_id: str,
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
    conn: Any, environment_id: str, new_text: str, base_text: str
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
                what=f"environments.settings for '{environment_id}'",
                get_recipe=_GET_RECIPE,
                merge_recipe=_MERGE_RECIPE,
            )
        )
    conn.commit()
    return f"Set settings for environment '{environment_id}'"


def cmd_environment_set_settings(
    environment_id: str,
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
    environment_id: str,
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
            what=f"settings for environment '{environment_id}'",
        )
        return (
            f"Merged {len(assignments)} key(s) into settings for "
            f"environment '{environment_id}'"
        )
    finally:
        conn.close()
