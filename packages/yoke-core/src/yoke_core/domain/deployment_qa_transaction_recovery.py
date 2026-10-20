"""Keep the triggering error visible when a deployment rollback loses its socket."""

from yoke_core.domain.connected_env_readiness import is_connection_unavailable_error
from yoke_core.domain.connected_env_readiness_connector import redact


def rollback_after_error(conn, original):
    try:
        conn.rollback()
    except Exception as rollback_error:
        detail = (
            f"original {type(original).__name__}: {redact(str(original))}; "
            f"rollback {type(rollback_error).__name__}: {redact(str(rollback_error))}"
        )
        if is_connection_unavailable_error(rollback_error):
            import psycopg

            raise psycopg.OperationalError(
                f"the connection is closed while recovering a deployment QA error; {detail}"
            ) from original
        original.add_note(detail)
        raise original from rollback_error
