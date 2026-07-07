"""Capability-settings surface: read/CAS-write/merge ``project_capabilities.settings``.

Owner: ``yoke_core.domain.projects`` (orchestration layer), mirroring
how :mod:`yoke_core.domain.projects_environments_settings` owns the
environment settings family; secrets and capability listings stay in
:mod:`yoke_core.domain.projects_capabilities`.

Writes are lost-update protected via value-CAS (the as-read settings text
is the base token — :mod:`yoke_core.domain.settings_cas`). The full
write requires exactly one of ``--base`` (CAS-update an existing row) or
``--new`` (insert-only create); a stale base or a lost create race raises
the typed :class:`~yoke_core.domain.settings_cas.SettingsConflictError`.
``capability-merge-settings`` updates single key paths through an internal
read-merge-CAS cycle (absent rows start from the empty object) so
concurrent writers compose instead of erasing each other.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from yoke_core.domain.db_helpers import (
    connect,
    iso8601_now,
    query_scalar,
)
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.projects_capability_settings_validation import (
    canonicalize_capability_settings,
)
from yoke_core.domain.settings_cas import (
    SETTINGS_CONFLICT_TAG,
    SettingsConflictError,
    base_required_teaching,
    cas_merge_loop,
    parse_set_assignments,
    parse_settings_object,
    settings_conflict_teaching,
)


CAPABILITY_SETTINGS_COMMANDS = (
    "capability-get-settings",
    "capability-set-settings",
    "capability-merge-settings",
)

_GET_RECIPE = (
    "python3 -m yoke_core.domain.projects capability-get-settings "
    "<project> <type>"
)
_MERGE_RECIPE = (
    "python3 -m yoke_core.domain.projects capability-merge-settings "
    "<project> <type> --set key.path=value"
)


def register_capability_settings_parsers(sub: Any) -> None:
    """Register the three subcommand parsers on the parent's subparser action."""
    p = sub.add_parser(
        "capability-get-settings",
        help=(
            "Get non-sensitive settings JSON (the printed text is the CAS "
            "base token for capability-set-settings)"
        ),
        description=(
            "Print the settings document for one capability. The exact "
            "printed text is the compare-and-swap base token for a "
            "full-document write: get -> edit -> capability-set-settings "
            "--base '<as-read-text>'. Exit 1 (no row) means create via "
            "capability-set-settings --new. Single-key updates skip the "
            "cycle via capability-merge-settings."
        ),
    )
    p.add_argument("project")
    p.add_argument("type")
    p = sub.add_parser(
        "capability-set-settings",
        help=(
            "CAS-write settings JSON (requires --base, the as-read text "
            "from capability-get-settings, or --new to create)"
        ),
        description=(
            "Full-document write, compare-and-swap protected: pass the "
            "exact text capability-get-settings printed as --base, or "
            "--new when the get exited 1 (no row yet). A stale base or a "
            "lost create race refuses with settings_conflict instead of "
            "silently erasing the newer write. Prefer "
            "capability-merge-settings for single-key updates."
        ),
    )
    p.add_argument("project")
    p.add_argument("type")
    p.add_argument("settings_json")
    p.add_argument(
        "--base",
        dest="base_settings_json",
        default=None,
        metavar="AS_READ_JSON",
        help=(
            "The exact settings text read via capability-get-settings; "
            "the write lands only while the stored text still equals it."
        ),
    )
    p.add_argument(
        "--new",
        dest="create",
        action="store_true",
        help=(
            "Insert-only create for a capability the get reported "
            "absent; refuses if the row appeared meanwhile."
        ),
    )
    p = sub.add_parser(
        "capability-merge-settings",
        help=(
            "Merge key.path=value assignments into capability settings "
            "(read-merge-CAS with one retry; creates absent rows)"
        ),
        description=(
            "Set individual keys without replacing the whole document: "
            "reads the current settings (absent rows start from {}), "
            "applies each --set key.path=value (value parsed as JSON when "
            "possible, raw string otherwise), and CAS-writes with one "
            "retry on conflict."
        ),
    )
    p.add_argument("project")
    p.add_argument("type")
    p.add_argument(
        "--set",
        dest="assignments",
        action="append",
        required=True,
        metavar="KEY.PATH=VALUE",
        help="Assignment to merge; repeatable.",
    )


def run_capability_settings_command(args: Any) -> int:
    """Dispatch one CAPABILITY_SETTINGS_COMMANDS member parsed by the parent."""
    if args.command == "capability-get-settings":
        result = cmd_capability_get_settings(args.project, args.type)
        if result is None:
            return 1
        print(result)
    elif args.command == "capability-set-settings":
        print(
            cmd_capability_set_settings(
                args.project, args.type, args.settings_json,
                base_settings_json=args.base_settings_json,
                create=args.create,
            )
        )
    else:
        print(
            cmd_capability_merge_settings(
                args.project, args.type,
                parse_set_assignments(args.assignments),
            )
        )
    return 0


def _canonicalize_capability_settings(cap_type: str, raw_json: str) -> str:
    """Route capability settings writes through per-type validators.

    Unknown types pass through unchanged (the open capability surface);
    structured types such as ``migration_model`` validate and
    canonicalize the payload before it reaches the DB.
    """
    return canonicalize_capability_settings(cap_type, raw_json)


def _read_settings_text(
    conn: Any, project_id: int, cap_type: str
) -> Optional[str]:
    """Return the as-read settings text, or None when no row exists."""
    val = query_scalar(
        conn,
        "SELECT COALESCE(settings, '{}') FROM project_capabilities "
        "WHERE project_id=%s AND type=%s",
        (project_id, cap_type),
    )
    if val is None or val == "":
        return None
    return str(val)


def cmd_capability_get_settings(
    project: str,
    cap_type: str,
    db_path: Optional[str] = None,
) -> Optional[str]:
    """Return non-sensitive settings JSON, or None if capability not found.

    The returned text doubles as the CAS base token for
    :func:`cmd_capability_set_settings`.
    """
    conn = connect(db_path)
    try:
        project_id = resolve_project_id(conn, project)
        return _read_settings_text(conn, project_id, cap_type)
    finally:
        conn.close()


def _cas_create(
    conn: Any, project: str, project_id: int, cap_type: str, new_text: str
) -> str:
    """Insert-only create; a row appearing concurrently refuses, typed."""
    cur = conn.execute(
        "INSERT INTO project_capabilities "
        "(project_id, type, settings, created_at) "
        "VALUES (%s, %s, %s, %s) "
        "ON CONFLICT(project_id, type) DO NOTHING",
        (project_id, cap_type, new_text, iso8601_now()),
    )
    if cur.rowcount == 0:
        conn.rollback()
        raise SettingsConflictError(
            f"{SETTINGS_CONFLICT_TAG}: capability '{cap_type}' on project "
            f"'{project}' already exists — --new declared it absent. "
            f"Re-read it ({_GET_RECIPE}) and retry with the fresh text as "
            f"--base, or use {_MERGE_RECIPE}."
        )
    conn.commit()
    return f"Created settings for capability '{cap_type}' on project '{project}'"


def _cas_update(
    conn: Any,
    project: str,
    project_id: int,
    cap_type: str,
    new_text: str,
    base_text: str,
) -> str:
    """CAS-update an existing row; commit on success, typed refusal otherwise."""
    cur = conn.execute(
        "UPDATE project_capabilities SET settings=%s "
        "WHERE project_id=%s AND type=%s AND COALESCE(settings, '{}')=%s",
        (new_text, project_id, cap_type, base_text),
    )
    if cur.rowcount == 0:
        missing = _read_settings_text(conn, project_id, cap_type) is None
        conn.rollback()
        if missing:
            raise SettingsConflictError(
                f"{SETTINGS_CONFLICT_TAG}: capability '{cap_type}' on "
                f"project '{project}' has no row for your --base to match "
                "— it was removed or never created. To create it pass "
                f"--new; otherwise re-read first ({_GET_RECIPE})."
            )
        raise SettingsConflictError(
            settings_conflict_teaching(
                what=(
                    f"settings for capability '{cap_type}' on project "
                    f"'{project}'"
                ),
                get_recipe=_GET_RECIPE,
                merge_recipe=_MERGE_RECIPE,
            )
        )
    conn.commit()
    return f"Set settings for capability '{cap_type}' on project '{project}'"


def cmd_capability_set_settings(
    project: str,
    cap_type: str,
    settings_json: str,
    *,
    base_settings_json: Optional[str] = None,
    create: bool = False,
    db_path: Optional[str] = None,
) -> str:
    """CAS-write non-sensitive settings for a capability.

    Exactly one of ``base_settings_json`` (the exact text read via
    :func:`cmd_capability_get_settings`; CAS-update) or ``create=True``
    (insert-only) is required — value-CAS protects against lost updates;
    no blind-upsert path exists.
    """
    has_base = bool(
        base_settings_json is not None and str(base_settings_json).strip()
    )
    if has_base == bool(create):
        raise ValueError(
            ("--base and --new are mutually exclusive. " if create else "")
            + base_required_teaching(
                get_recipe=_GET_RECIPE, merge_recipe=_MERGE_RECIPE
            )
            + " When the get exits 1 (no row yet), pass --new instead of --base."
        )
    settings_json = _canonicalize_capability_settings(cap_type, settings_json)
    parse_settings_object(settings_json, what="settings JSON")
    conn = connect(db_path)
    try:
        project_id = resolve_project_id(conn, project)
        if create:
            return _cas_create(conn, project, project_id, cap_type, settings_json)
        return _cas_update(
            conn, project, project_id, cap_type, settings_json,
            str(base_settings_json),
        )
    finally:
        conn.close()


def cmd_capability_merge_settings(
    project: str,
    cap_type: str,
    assignments: Dict[str, Any],
    db_path: Optional[str] = None,
) -> str:
    """Merge dot-path assignments into capability settings (CAS, one retry).

    Absent capabilities start from the empty object and are created
    insert-only, so the merge surface is the universal single-key repair
    recipe for both existing and missing rows.
    """
    conn = connect(db_path)
    try:
        project_id = resolve_project_id(conn, project)

        def read_current() -> Optional[str]:
            return _read_settings_text(conn, project_id, cap_type)

        def cas_write(base: Optional[str], merged_text: str) -> str:
            merged_text = _canonicalize_capability_settings(cap_type, merged_text)
            if base is None:
                return _cas_create(conn, project, project_id, cap_type, merged_text)
            return _cas_update(
                conn, project, project_id, cap_type, merged_text, base
            )

        cas_merge_loop(
            read_current=read_current,
            cas_write=cas_write,
            assignments=assignments,
            what=f"settings for capability '{cap_type}' on project '{project}'",
        )
        return (
            f"Merged {len(assignments)} key(s) into settings for capability "
            f"'{cap_type}' on project '{project}'"
        )
    finally:
        conn.close()
