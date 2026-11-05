"""Project posts addressed to live audiences, with atomic shared Done."""

from __future__ import annotations

import json
from typing import Any

from yoke_contracts.refusal_recovery import compose_refusal
from yoke_contracts.timestamps import utc_now
from yoke_core.domain import audiences
from yoke_core.domain.actor_permissions import (
    PERM_ITEMS_READ,
    PERM_ITEMS_WRITE,
    permission_decision,
)
from yoke_core.domain.actor_render import actor_display_labels
from yoke_core.domain.db_helpers import instant_parameter
from yoke_core.domain.db_savepoint import savepoint


def _permission(conn: Any, actor_id: int, project_id: int, key: str) -> None:
    if not permission_decision(
        conn, actor_id=actor_id, project_id=project_id, permission_key=key
    ).allowed:
        raise PermissionError(
            compose_refusal(
                f"permission_denied: This project requires {key}",
                recovery="Ask the project owner to grant the required project permission, then retry",
            )
        )


def _row(conn: Any, post_id: int) -> dict:
    row = conn.execute(
        f"SELECT * FROM inbox_posts WHERE id = {audiences._p(conn)}", (post_id,)
    ).fetchone()
    if row is None:
        raise LookupError(
            compose_refusal(
                "unknown_post: The Inbox post does not exist",
                recovery="Reload the Inbox and select an existing post",
            )
        )
    result = dict(row)
    result["fields"] = json.loads(result["fields"])
    if result["done_actor_id"] is not None:
        result["done_by"] = actor_display_labels(conn, (result["done_actor_id"],))[
            result["done_actor_id"]
        ]
    return result


def create_post(
    conn: Any,
    *,
    actor_id: int,
    project_id: int,
    title: str,
    body: str,
    source: str,
    fields: dict[str, Any] | None = None,
    audience_id: int | None = None,
    audience_name: str | None = None,
    rules: list[dict] | None = None,
    commit: bool = True,
) -> dict:
    _permission(conn, actor_id, project_id, PERM_ITEMS_WRITE)
    if not title.strip() or not source.strip():
        raise ValueError(
            compose_refusal(
                "invalid_post: Title and source are required",
                recovery="Supply a title and source label",
            )
        )
    if sum(value is not None for value in (audience_id, audience_name, rules)) != 1:
        raise ValueError(
            compose_refusal(
                "invalid_audience: Choose one audience",
                recovery="Supply audience_id, audience_name, or inline rules",
            )
        )
    p = audiences._p(conn)
    audiences.begin_write(conn)
    with savepoint(conn, "inbox_post_create", owns=commit):
        if audience_name is not None:
            row = conn.execute(
                f"SELECT id FROM audiences WHERE project_id = {p} AND name = {p}",
                (project_id, audience_name),
            ).fetchone()
            if row is None:
                raise ValueError(
                    compose_refusal(
                        "unknown_audience: No audience has that name",
                        recovery="List audiences for this project and select an existing name",
                    )
                )
            audience_id = int(row[0])
        if rules is not None:
            audience_id = audiences.create_audience(
                conn, project_id=project_id, rules=rules, commit=False
            )
        owner = audiences.audience(conn, audience_id)
        if owner["project_id"] != project_id:
            raise ValueError(
                compose_refusal(
                    "audience_scope_mismatch: The audience belongs to another scope",
                    recovery="Select an audience owned by this project",
                )
            )
        if not audiences.rules_for_audiences(conn, (audience_id,)).get(audience_id):
            raise ValueError(
                compose_refusal(
                    "empty_audience: The audience has no rules",
                    recovery="Select an audience with at least one rule",
                )
            )
        post_id = conn.execute(
            "INSERT INTO inbox_posts(project_id, audience_id, title, body, fields, source, created_by_actor_id, created_at) "
            f"VALUES ({','.join(p for _ in range(8))}) RETURNING id",
            (
                project_id,
                audience_id,
                title.strip(),
                body,
                json.dumps(fields or {}),
                source.strip(),
                actor_id,
                instant_parameter(conn, utc_now()),
            ),
        ).fetchone()[0]
        result = _row(conn, post_id)
    if commit:
        conn.commit()
    return result


def done_post(conn: Any, *, post_id: int, actor_id: int, commit: bool = True) -> dict:
    post = _row(conn, post_id)
    _permission(conn, actor_id, post["project_id"], PERM_ITEMS_READ)
    if not audiences.includes_actor(conn, post["audience_id"], actor_id):
        raise PermissionError(
            compose_refusal(
                "not_in_audience: This post is addressed to other people",
                recovery="Ask a current audience member to mark it Done",
            )
        )
    p = audiences._p(conn)
    audiences.begin_write(conn)
    with savepoint(conn, "inbox_post_done", owns=commit):
        changed = (
            conn.execute(
                f"UPDATE inbox_posts SET done_actor_id = {p}, done_at = {p} WHERE id = {p} AND done_at IS NULL RETURNING id",
                (actor_id, instant_parameter(conn, utc_now()), post_id),
            ).fetchone()
            is not None
        )
        result = _row(conn, post_id)
        result["already_done"] = not changed
    if commit:
        conn.commit()
    return result


def open_posts(
    conn: Any, *, actor_id: int, project_ids: list[int] | None = None
) -> list[dict]:
    ids = audiences.audiences_for_actor(conn, actor_id)
    if not ids:
        return []
    p = audiences._p(conn)
    rows = conn.execute(
        f"SELECT * FROM inbox_posts WHERE done_at IS NULL AND audience_id IN ({','.join(p for _ in ids)}) ORDER BY created_at DESC, id DESC",
        ids,
    ).fetchall()
    readable = {}
    result = []
    for row in rows:
        project_id = int(row["project_id"])
        if project_ids is not None and project_id not in project_ids:
            continue
        if project_id not in readable:
            readable[project_id] = permission_decision(
                conn,
                actor_id=actor_id,
                project_id=project_id,
                permission_key=PERM_ITEMS_READ,
            ).allowed
        if readable[project_id]:
            post = dict(row)
            post["fields"] = json.loads(post["fields"])
            result.append(post)
    return result
