"""Core authentication logic for {{project_display_name}} API."""

import secrets
from datetime import timedelta
from typing import Optional

import bcrypt

from utils.db import get_connection
from utils.timestamps import format_instant, parse_instant, utc_now


SESSION_EXPIRY_DAYS = 7


def hash_password(password: str) -> str:
    """Hash a password with bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its bcrypt hash."""
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def create_session(user_id: int) -> str:
    """Create a new session and return the session ID."""
    session_id = secrets.token_hex(32)
    created_at = parse_instant(utc_now())
    expires_at = created_at + timedelta(days=SESSION_EXPIRY_DAYS)

    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO sessions (id, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
            (
                session_id,
                user_id,
                format_instant(expires_at),
                format_instant(created_at),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return session_id


def validate_session(session_id: str) -> Optional[dict]:
    """Validate a session ID and return the user dict, or None if invalid."""
    conn = get_connection()
    try:
        row = conn.execute(
            """SELECT u.id, u.email, u.name, u.role, s.expires_at
               FROM sessions s
               JOIN users u ON s.user_id = u.id
               WHERE s.id = ?""",
            (session_id,),
        ).fetchone()
        if row and parse_instant(row["expires_at"]) > parse_instant(utc_now()):
            return {key: row[key] for key in ("id", "email", "name", "role")}
        return None
    finally:
        conn.close()


def validate_api_key(api_key: str) -> Optional[dict]:
    """Validate an API key and return the user dict, or None if invalid."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id, email, name, role FROM users WHERE api_key = ?",
            (api_key,),
        ).fetchone()
        if row:
            return dict(row)
        return None
    finally:
        conn.close()


def delete_session(session_id: str) -> bool:
    """Delete a session. Returns True if a row was deleted."""
    conn = get_connection()
    try:
        cursor = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def get_user_by_email(email: str) -> Optional[dict]:
    """Look up a user by email. Returns full user dict including password_hash."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id, email, password_hash, name, role, api_key FROM users WHERE email = ?",
            (email,),
        ).fetchone()
        if row:
            return dict(row)
        return None
    finally:
        conn.close()


def get_user_orgs(user_id: int) -> list:
    """Get org memberships for a user."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT o.id, o.name, o.slug, om.role
               FROM org_members om
               JOIN orgs o ON om.org_id = o.id
               WHERE om.user_id = ?""",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def generate_api_key() -> str:
    """Generate a random API key."""
    return "{{project_name}}_" + secrets.token_hex(24)


def update_password(user_id: int, new_password_hash: str) -> bool:
    """Update a user's password hash. Returns True if a row was updated."""
    conn = get_connection()
    try:
        cursor = conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (new_password_hash, user_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def set_api_key(user_id: int, api_key: str) -> bool:
    """Set or replace a user's API key. Returns True if a row was updated."""
    conn = get_connection()
    try:
        cursor = conn.execute(
            "UPDATE users SET api_key = ? WHERE id = ?",
            (api_key, user_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def get_user_api_key(user_id: int) -> Optional[str]:
    """Get a user's current API key, or None if not set."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT api_key FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if row:
            return row["api_key"]
        return None
    finally:
        conn.close()
