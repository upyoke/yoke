"""FastAPI dependencies for {{project_display_name}} API."""

import sys
import os
from typing import Generator

from fastapi import Depends, HTTPException, Request

# Ensure app/ is on sys.path so utils/ imports work
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

from utils.db import get_connection


def get_db() -> Generator:
    """Yield a DB connection, close after request."""
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


def get_current_user(request: Request) -> dict:
    """Extract and validate auth from cookie or Bearer header.

    Returns user dict: {id, email, name, role}.
    Raises 401 if no valid auth found.
    """
    from api.auth import validate_session, validate_api_key

    # Try cookie first
    session_id = request.cookies.get("{{project_name}}_session")
    if session_id:
        user = validate_session(session_id)
        if user:
            return user

    # Try API key header
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        api_key = auth_header[7:]
        user = validate_api_key(api_key)
        if user:
            return user

    raise HTTPException(
        status_code=401,
        detail={"code": "ERR_UNAUTHORIZED", "message": "Authentication required"},
    )
