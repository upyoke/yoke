"""Reads behind the Profile page: one actor's own identity, roles,
tokens, preferences, and hidden Overview modules.

Every read takes the bound actor id and returns plain dictionaries the
page renders directly; nothing here consults any other actor's rows.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

from yoke_core.domain.overview_activation_read import DISMISS_PREF_PREFIX


#: ``actor_ui_preferences.pref_key`` for the time-zone override. An empty
#: value (or no row) means "Automatic": the browser's own zone.
TIME_ZONE_PREF_KEY = "profile.time_zone"

#: Sign-in issuers a person recognises by product name rather than by URL.
_ISSUER_LABELS = (
    ("google", "Google"),
    ("github", "GitHub"),
    ("microsoft", "Microsoft"),
)


def issuer_label(issuer: str) -> str:
    """Name a sign-in issuer the way a person would say it."""
    lowered = (issuer or "").lower()
    for needle, label in _ISSUER_LABELS:
        if needle in lowered:
            return label
    host = urlsplit(issuer).netloc if "://" in (issuer or "") else issuer
    return host or "unknown"


def read_actor(conn: Any, actor_id: int) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        "SELECT id, kind, name, system_component FROM actors WHERE id = %s",
        (actor_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "id": int(row[0]),
        "kind": row[1],
        "name": row[2] or row[3] or f"actor {row[0]}",
    }


def read_identity(conn: Any, actor_id: int) -> Optional[Dict[str, Any]]:
    """The newest linked sign-in identity, or None when the actor has none."""
    row = conn.execute(
        "SELECT issuer, email FROM actor_external_identities "
        "WHERE actor_id = %s ORDER BY linked_at DESC, id DESC LIMIT 1",
        (actor_id,),
    ).fetchone()
    if row is None:
        return None
    return {"email": row[1] or None, "signed_in_with": issuer_label(row[0])}


def read_roles(conn: Any, actor_id: int) -> Dict[str, List[Dict[str, Any]]]:
    org_rows = conn.execute(
        "SELECT o.name, r.name FROM actor_org_roles aor "
        "JOIN organizations o ON o.id = aor.org_id "
        "JOIN roles r ON r.id = aor.role_id "
        "WHERE aor.actor_id = %s ORDER BY o.name, r.name",
        (actor_id,),
    ).fetchall()
    project_rows = conn.execute(
        "SELECT p.slug, p.name, r.name FROM actor_project_roles apr "
        "JOIN projects p ON p.id = apr.project_id "
        "JOIN roles r ON r.id = apr.role_id "
        "WHERE apr.actor_id = %s ORDER BY p.slug, r.name",
        (actor_id,),
    ).fetchall()
    return {
        "org": [{"org": row[0], "role": row[1]} for row in org_rows],
        "projects": [
            {"project": row[0], "name": row[1], "role": row[2]}
            for row in project_rows
        ],
    }


def read_tokens(conn: Any, actor_id: int) -> List[Dict[str, Any]]:
    """The actor's live tokens, newest first; a machine token names its machine."""
    rows = conn.execute(
        "SELECT t.id, t.name, t.status, t.created_at, t.last_used_at, "
        "t.expires_at, t.machine_id, m.name FROM api_tokens t "
        "LEFT JOIN machines m ON m.machine_id = t.machine_id "
        "WHERE t.actor_id = %s AND t.status = 'active' "
        "ORDER BY t.created_at DESC, t.id DESC",
        (actor_id,),
    ).fetchall()
    return [
        {
            "token_id": int(row[0]),
            "name": row[1],
            "status": row[2],
            "created_at": row[3],
            "last_used_at": row[4],
            "expires_at": row[5],
            "machine_id": row[6],
            "machine_name": row[7],
        }
        for row in rows
    ]


def read_preferences(conn: Any, actor_id: int) -> Dict[str, Any]:
    row = conn.execute(
        "SELECT value FROM actor_ui_preferences "
        "WHERE actor_id = %s AND pref_key = %s",
        (actor_id, TIME_ZONE_PREF_KEY),
    ).fetchone()
    return {"time_zone": (row[0] if row else "") or ""}


def hidden_module_count(conn: Any, actor_id: int) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM actor_ui_preferences "
        "WHERE actor_id = %s AND pref_key LIKE %s",
        (actor_id, DISMISS_PREF_PREFIX + "%"),
    ).fetchone()
    return int(row[0]) if row else 0


__all__ = [
    "TIME_ZONE_PREF_KEY",
    "hidden_module_count",
    "issuer_label",
    "read_actor",
    "read_identity",
    "read_preferences",
    "read_roles",
    "read_tokens",
]
