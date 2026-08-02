"""Durable outcome receipts for project-scoped GitHub automation."""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from functools import wraps
from threading import Lock
from typing import Any, Callable, Optional

from yoke_core.domain import control_plane_transport, db_backend
from yoke_core.domain.db_helpers import connect, iso8601_now
from yoke_core.domain.project_identity import resolve_project


RECORD_FUNCTION_ID = "projects.github_sync_receipt.record"

_MAX_TRACKED_TOKENS = 256
_token_projects: OrderedDict[str, tuple[str, Optional[str]]] = OrderedDict()
_token_projects_lock = Lock()


def register_installation_token(
    token: str,
    project: str,
    *,
    db_path: Optional[str] = None,
) -> None:
    """Associate a process-local installation token with its project."""
    digest = _token_digest(token)
    if not digest or not project:
        return
    with _token_projects_lock:
        _token_projects[digest] = (project, db_path)
        _token_projects.move_to_end(digest)
        while len(_token_projects) > _MAX_TRACKED_TOKENS:
            _token_projects.popitem(last=False)


def record_installation_token_result(
    token: str,
    *,
    outcome: str,
    error: str = "",
) -> bool:
    """Persist a terminal GitHub REST result when the token is project-bound."""
    if outcome not in {"success", "failed"}:
        raise ValueError("GitHub sync outcome must be success or failed")
    digest = _token_digest(token)
    with _token_projects_lock:
        target = _token_projects.get(digest)
    if target is None:
        return False
    project, db_path = target
    conn = control_plane_transport.local_connection_or_none(
        lambda: connect(db_path)
    )
    if conn is None:
        # No local authority — an https control plane is the ordinary case
        # here, not a failure, so the receipt relays rather than being lost.
        try:
            return bool(
                control_plane_transport.relay(
                    RECORD_FUNCTION_ID,
                    {"project": project, "outcome": outcome, "error": error},
                ).get("recorded")
            )
        except Exception:
            return False
    try:
        return record_over_connection(
            conn, project, outcome=outcome, error=error,
        )
    except Exception:
        return False
    finally:
        conn.close()


def record_over_connection(
    conn: Any,
    project: str,
    *,
    outcome: str,
    error: str = "",
) -> bool:
    """Stamp the terminal sync result through an already-open connection."""
    identity = resolve_project(conn, project, required=True)
    assert identity is not None
    placeholder = "%s" if db_backend.connection_is_postgres(conn) else "?"
    conn.execute(
        "UPDATE project_github_repo_bindings SET "
        f"last_sync_at={placeholder}, last_sync_outcome={placeholder}, "
        f"last_sync_error={placeholder} WHERE project_id={placeholder}",
        (iso8601_now(), outcome, error if outcome == "failed" else "", identity.id),
    )
    conn.commit()
    return True


def with_installation_token_receipt(
    request: Callable[..., Any],
) -> Callable[..., Any]:
    """Wrap the canonical REST executor with durable terminal receipts."""
    @wraps(request)
    def tracked(req, *, token, timeout_seconds=30.0, max_attempts=None):
        try:
            response = request(
                req,
                token=token,
                timeout_seconds=timeout_seconds,
                max_attempts=max_attempts,
            )
        except Exception as exc:
            record_installation_token_result(
                token,
                outcome="failed",
                error=type(exc).__name__,
            )
            raise
        record_installation_token_result(token, outcome="success")
        return response

    return tracked


def _token_digest(token: str) -> str:
    value = str(token or "").encode("utf-8")
    return hashlib.sha256(value).hexdigest() if value else ""


__all__ = [
    "RECORD_FUNCTION_ID",
    "record_installation_token_result",
    "record_over_connection",
    "register_installation_token",
    "with_installation_token_receipt",
]
