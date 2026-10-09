"""CAS-protected reads, writes, merges, and removals for capability settings.

Generic capabilities support full compare-and-swap replacement and key-path
merge. GitHub settings are binding-owned: generic full writes are closed and
merge admits only the documented optional boolean on a canonical binding.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from yoke_core.domain.db_helpers import (
    connect,
    instant_parameter,
    utc_now,
    query_scalar,
)
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.projects_capabilities_settings_cli import (
    register_capability_settings_parsers as register_capability_settings_parsers,
)
from yoke_core.domain.project_github_capability_settings import (
    assert_github_capability_merge_target,
    reject_github_capability_full_settings_write,
    validate_github_capability_merge_assignments,
)
from yoke_core.domain.projects_capability_settings_validation import (
    canonicalize_capability_settings,
)
from yoke_core.domain.pulumi_state_capability import (
    reject_generic_full_write as reject_pulumi_state_full_write,
    reject_generic_read as reject_pulumi_state_read,
    validate_merge_assignments as validate_pulumi_state_merge_assignments,
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
    "capability-remove-settings",
)

_GET_RECIPE = (
    "yoke projects capability-settings get --project <project> --cap-type <type>"
)
_MERGE_RECIPE = (
    "yoke projects capability-settings merge --project <project> "
    "--cap-type <type> --set key.path=value"
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
                args.project,
                args.type,
                args.settings_json,
                base_settings_json=args.base_settings_json,
                create=args.create,
            )
        )
    elif args.command == "capability-merge-settings":
        print(
            cmd_capability_merge_settings(
                args.project,
                args.type,
                parse_set_assignments(args.assignments),
            )
        )
    else:
        print(
            cmd_capability_remove_settings(
                args.project,
                args.type,
                base_settings_json=args.base_settings_json,
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


def _read_settings_text(conn: Any, project_id: int, cap_type: str) -> Optional[str]:
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
    cap_type = reject_pulumi_state_read(cap_type)
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
        (project_id, cap_type, new_text, instant_parameter(conn, utc_now())),
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
                what=(f"settings for capability '{cap_type}' on project '{project}'"),
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
    cap_type = reject_github_capability_full_settings_write(cap_type)
    cap_type = reject_pulumi_state_full_write(cap_type)
    has_base = bool(base_settings_json is not None and str(base_settings_json).strip())
    if has_base == bool(create):
        raise ValueError(
            ("--base and --new are mutually exclusive. " if create else "")
            + base_required_teaching(get_recipe=_GET_RECIPE, merge_recipe=_MERGE_RECIPE)
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
            conn,
            project,
            project_id,
            cap_type,
            settings_json,
            str(base_settings_json),
        )
    finally:
        conn.close()


def cmd_capability_remove_settings(
    project: str,
    cap_type: str,
    *,
    base_settings_json: str,
    db_path: Optional[str] = None,
) -> str:
    """CAS-remove one ordinary capability without blind deletion.

    GitHub bindings and Pulumi operator state have dedicated ownership
    lifecycles and cannot be removed through this generic settings surface.
    """
    cap_type = reject_github_capability_full_settings_write(cap_type)
    cap_type = reject_pulumi_state_full_write(cap_type)
    base_text = str(base_settings_json or "")
    if not base_text.strip():
        raise ValueError(
            "--base is required; read the exact current document with " + _GET_RECIPE
        )
    conn = connect(db_path)
    try:
        project_id = resolve_project_id(conn, project)
        cur = conn.execute(
            "DELETE FROM project_capabilities WHERE project_id=%s AND type=%s "
            "AND COALESCE(settings, '{}')=%s",
            (project_id, cap_type, base_text),
        )
        if cur.rowcount == 0:
            missing = _read_settings_text(conn, project_id, cap_type) is None
            conn.rollback()
            if missing:
                raise LookupError(
                    f"capability '{cap_type}' was not found on project '{project}'"
                )
            raise SettingsConflictError(
                settings_conflict_teaching(
                    what=(
                        f"settings for capability '{cap_type}' on project '{project}'"
                    ),
                    get_recipe=_GET_RECIPE,
                    merge_recipe=_MERGE_RECIPE,
                )
            )
        conn.commit()
        return f"Removed capability '{cap_type}' from project '{project}'"
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
    cap_type = validate_github_capability_merge_assignments(cap_type, assignments)
    cap_type = validate_pulumi_state_merge_assignments(cap_type, assignments)
    conn = connect(db_path)
    try:
        project_id = resolve_project_id(conn, project)
        assert_github_capability_merge_target(conn, project_id, cap_type)

        def read_current() -> Optional[str]:
            return _read_settings_text(conn, project_id, cap_type)

        def cas_write(base: Optional[str], merged_text: str) -> str:
            assert_github_capability_merge_target(conn, project_id, cap_type)
            merged_text = _canonicalize_capability_settings(cap_type, merged_text)
            if base is None:
                return _cas_create(conn, project, project_id, cap_type, merged_text)
            return _cas_update(conn, project, project_id, cap_type, merged_text, base)

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
