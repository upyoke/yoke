"""Current session identity for domain callers."""

from yoke_core.domain.session_ambient_identity import resolve_ambient_session_id


def current_session_id() -> str:
    """Return the ambient session, or an empty string outside a session."""
    return resolve_ambient_session_id() or ""
