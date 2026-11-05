"""Compose human session labels from current facts at read time."""

from collections import defaultdict

from yoke_contracts.timestamps import parse_instant, utc_now
from yoke_core.domain.item_ref_render import render_item_refs
from yoke_core.domain.project_identity import placeholder
from yoke_core.domain.work_claim_targets import from_row


def session_display_details(conn, session_ids):
    ids = tuple(dict.fromkeys(str(value) for value in session_ids if value))
    if not ids:
        return {}
    p = placeholder(conn)
    slots = ",".join(p for _ in ids)
    sessions = conn.execute(
        "SELECT s.*,p.slug AS project_slug FROM harness_sessions s "
        "LEFT JOIN projects p ON p.id=s.project_id "
        f"WHERE s.session_id IN ({slots})",
        ids,
    ).fetchall()
    launches = conn.execute(
        "SELECT registered_session_id,native_session_id,item_id FROM session_launches "
        f"WHERE registered_session_id IN ({slots}) OR native_session_id IN ({slots}) "
        "ORDER BY created_at DESC,launch_id DESC",
        (*ids, *ids),
    ).fetchall()
    claims = conn.execute(
        "SELECT * FROM work_claims "
        f"WHERE session_id IN ({slots}) "
        "ORDER BY released_at DESC,claimed_at DESC,id DESC",
        ids,
    ).fetchall()
    targets = [(dict(row), from_row(dict(row))) for row in claims]
    item_ids = {row["item_id"] for row in launches if row["item_id"] is not None}
    item_ids.update(
        target.item_id or target.epic_id
        for _, target in targets
        if target.kind in {"item", "epic_task"}
    )
    refs = render_item_refs(conn, item_ids)
    items = {}
    if item_ids:
        holes = ",".join(p for _ in item_ids)
        items = {
            row["id"]: dict(row)
            for row in conn.execute(
                f"SELECT * FROM items WHERE id IN ({holes})",
                tuple(item_ids),
            ).fetchall()
        }
    launched = {}
    for row in launches:
        item_id = row["item_id"]
        if item_id not in refs:
            continue
        title = items.get(item_id, {}).get("title") or ""
        for session_id in (row["registered_session_id"], row["native_session_id"]):
            if session_id:
                launched.setdefault(session_id, f"{refs[item_id]} {title}".strip())
    current, recent = defaultdict(list), {}
    for row, target in targets:
        if target.kind not in {"item", "epic_task"}:
            continue
        item_id = target.item_id or target.epic_id
        if item_id not in refs:
            continue
        title = items.get(item_id, {}).get("title") or ""
        if row["released_at"] is None:
            text = f"holds {refs[item_id]} '{title}'"
            if text not in current[row["session_id"]]:
                current[row["session_id"]].append(text)
        else:
            recent.setdefault(row["session_id"], f"held {refs[item_id]}")
    now = utc_now()
    details = {}
    for raw in sessions:
        row = dict(raw)
        session_id = row["session_id"]
        title = row.get("harness_title") or launched.get(session_id)
        parts = [title] if title else []
        parts.extend(
            [
                row.get("executor_surface")
                or row.get("executor")
                or "harness unavailable",
                row["project_slug"] or "outside a project",
            ]
        )
        parts.extend(
            current[session_id]
            or ([recent[session_id]] if session_id in recent else [])
        )
        stamps = [
            parse_instant(row[key])
            for key in ("last_tool_call_at", "last_heartbeat")
            if row.get(key)
        ]
        if stamps:
            seconds = max(0, int((now - max(stamps)).total_seconds()))
            age = (
                f"{seconds}s"
                if seconds < 60
                else f"{seconds // 60}m"
                if seconds < 3600
                else f"{seconds // 3600}h"
                if seconds < 86400
                else f"{seconds // 86400}d"
            )
            parts.append(f"active {age} ago")
        details[session_id] = {"title": title, "label": " · ".join(parts)}
    return details


def session_display_names(conn, session_ids) -> dict[str, str]:
    return {
        key: value["label"]
        for key, value in session_display_details(conn, session_ids).items()
    }


def session_display_name(conn, session_id) -> str:
    return session_display_names(conn, [session_id]).get(
        session_id, "session unavailable"
    )
