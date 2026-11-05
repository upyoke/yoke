"""Decision request askers use the shared human session label."""

from yoke_core.domain.session_display import session_display_names


def requester_labels(conn, session_ids) -> dict[str, str]:
    return session_display_names(conn, session_ids)
