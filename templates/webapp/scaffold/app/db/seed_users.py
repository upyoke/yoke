#!/usr/bin/env python3
"""Seed the default org and superadmin user for {{project_display_name}} API.

Usage:
    python3 db/seed_users.py [--db-path PATH]

Requires APP_ADMIN_PASSWORD env var (or prompts interactively).
Safe to re-run: skips existing records.
"""

import os
import sys

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP_DIR)

from utils.db import get_connection


def seed_users(db_path=None):
    """Create default org + superadmin user. Idempotent."""
    # Get password from env or prompt
    password = os.environ.get("APP_ADMIN_PASSWORD", "")
    if not password:
        try:
            import getpass
            password = getpass.getpass("Enter admin password for admin@{{project_name}}.local: ")
        except (EOFError, KeyboardInterrupt):
            return {"status": "error", "error": "Password required (set APP_ADMIN_PASSWORD)"}

    if not password:
        return {"status": "error", "error": "Password cannot be empty"}

    # Import auth after path setup
    from api.auth import hash_password, generate_api_key

    conn = get_connection(db_path=db_path)
    try:
        created = []

        # 1. Ensure "Default" org exists
        row = conn.execute("SELECT id FROM orgs WHERE slug = ?", ("default",)).fetchone()
        if row:
            org_id = row["id"]
        else:
            cursor = conn.execute(
                "INSERT INTO orgs (name, slug) VALUES (?, ?)",
                ("Default", "default"),
            )
            org_id = cursor.lastrowid
            created.append("org:Default")

        # 2. Ensure superadmin user exists
        row = conn.execute("SELECT id FROM users WHERE email = ?", ("admin@{{project_name}}.local",)).fetchone()
        if row:
            user_id = row["id"]
        else:
            api_key = generate_api_key()
            cursor = conn.execute(
                "INSERT INTO users (email, password_hash, name, role, api_key) VALUES (?, ?, ?, ?, ?)",
                ("admin@{{project_name}}.local", hash_password(password), "Admin", "superadmin", api_key),
            )
            user_id = cursor.lastrowid
            created.append(f"user:admin@{{project_name}}.local (api_key={api_key})")

        # 3. Ensure org membership
        row = conn.execute(
            "SELECT * FROM org_members WHERE org_id = ? AND user_id = ?",
            (org_id, user_id),
        ).fetchone()
        if not row:
            conn.execute(
                "INSERT INTO org_members (org_id, user_id, role) VALUES (?, ?, ?)",
                (org_id, user_id, "owner"),
            )
            created.append("org_member:owner")

        conn.commit()

        return {
            "status": "ok",
            "data": {
                "org_id": org_id,
                "user_id": user_id,
                "created": created if created else ["all_exists"],
            },
        }
    finally:
        conn.close()


def main():
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Seed {{project_display_name}} API users")
    parser.add_argument("--db-path", help="Path to SQLite database file")
    args = parser.parse_args()

    result = seed_users(db_path=args.db_path)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["status"] == "ok" else 1)


if __name__ == "__main__":
    main()
