"""Collapsed local finalization side effects for done-transition."""

from __future__ import annotations

from yoke_core.domain import db_backend


def _parent():
    from yoke_core.engines import done_transition as _dt
    return _dt


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _finalize_done_local_side_effects(
    item_id: int,
    item_type: str,
    title: str,
    item_project: str,
    env_name: str,
) -> None:
    """Run local DB-only done side effects with one control-plane connection."""
    print("\n=== Step 6c/6d/7/10: Local done finalization ===")
    try:
        with _parent()._connect() as conn:
            released = _release_done_claims(conn, item_id)
            rows = _stop_ephemeral_envs(conn, item_id)
            deployed_to = _resolve_deployed_to(conn, item_id, env_name)
            if deployed_to:
                p = _p(conn)
                conn.execute(
                    f"UPDATE items SET deployed_to = {p} WHERE id = {p}",
                    (deployed_to, item_id),
                )
            release_note = _insert_release_note(conn, item_id, item_type, title, item_project)
            conn.commit()
    except db_backend.operational_error_types() as exc:
        print(f"Advisory: local done finalization partly skipped: {exc}")
        return
    except Exception as exc:  # pragma: no cover - defensive
        print(f"Advisory: local done finalization failed: {exc}")
        return

    claim_msg = (
        f"released {released} work claim(s)" if released else "no orphaned claims"
    )
    env_msg = f"stopped {rows} ephemeral env(s)" if rows else "no active ephemeral envs"
    deploy_msg = f"deployed_to={deployed_to}" if deployed_to else "deployed_to unchanged"
    note_msg = "release note upserted" if release_note else "release note skipped"
    print(f"Local finalization: {claim_msg}; {env_msg}; {deploy_msg}; {note_msg}.")


def _release_done_claims(conn, item_id: int) -> int:
    from yoke_core.domain import sessions as _sessions_domain

    try:
        return int(_sessions_domain.release_claims_for_done_item(conn, f"YOK-{item_id}"))
    except db_backend.operational_error_types(conn):
        return 0


def _stop_ephemeral_envs(conn, item_id: int) -> int:
    from yoke_core.domain.db_helpers import iso8601_now

    try:
        p = _p(conn)
        rows = conn.execute(
            "SELECT id FROM ephemeral_environments "
            f"WHERE item = {p} AND status <> 'stopped'",
            (f"YOK-{item_id}",),
        ).fetchall()
    except db_backend.operational_error_types(conn):
        return 0
    if not rows:
        return 0
    for row in rows:
        conn.execute(
            f"UPDATE ephemeral_environments SET status = 'stopped', stopped_at = {p} "
            f"WHERE id = {p}",
            (iso8601_now(), int(row[0])),
        )
    return len(rows)


def _resolve_deployed_to(conn, item_id: int, env_name: str) -> str:
    if env_name:
        return env_name
    try:
        p = _p(conn)
        row = conn.execute(
            "SELECT COALESCE(i.deployment_flow, ''), COALESCE(f.target_env, '') "
            "FROM items i "
            "LEFT JOIN deployment_flows f ON f.id = i.deployment_flow "
            f"WHERE i.id = {p}",
            (item_id,),
        ).fetchone()
    except db_backend.operational_error_types(conn):
        return ""
    if not row:
        return ""
    deploy_flow, target_env = str(row[0] or ""), str(row[1] or "")
    if deploy_flow and deploy_flow != "null" and target_env and target_env != "null":
        return target_env
    return ""


def _insert_release_note(
    conn,
    item_id: int,
    item_type: str,
    title: str,
    item_project: str,
) -> bool:
    from yoke_core.domain import release_notes as _release_notes

    category = "improvements"
    if item_type == "epic":
        category = "features"
    elif item_type == "issue":
        category = "bug_fixes"
    try:
        _release_notes.cmd_insert(
            conn,
            int(item_id),
            category,
            title,
            project=item_project or None,
        )
    except db_backend.operational_error_types(conn):
        return False
    return True


__all__ = ["_finalize_done_local_side_effects"]
