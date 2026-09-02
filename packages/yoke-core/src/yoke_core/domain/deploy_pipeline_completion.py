"""Transactional completion events emitted by deployment pipeline outcomes."""

from typing import Any, Mapping


def emit_completion(
    run_id: str,
    event_name: str,
    outcome: str,
    context: Mapping[str, Any],
) -> str:
    """Commit one terminal deployment-run event atomically."""
    from yoke_core.domain import deployment_approval_requests
    from yoke_core.domain.db_helpers import connect

    conn = connect()
    try:
        event_id = deployment_approval_requests.emit_deployment_completion(
            conn,
            run_id=run_id,
            event_name=event_name,
            outcome=outcome,
            context=context,
        )
        conn.commit()
        return event_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

__all__ = ["emit_completion"]
