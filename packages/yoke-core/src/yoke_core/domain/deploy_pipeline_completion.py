"""Transactional completion events emitted by deployment pipeline outcomes."""

from typing import Any, Mapping


def emit_completion(
    run_id: str,
    event_name: str,
    outcome: str,
    context: Mapping[str, Any],
) -> tuple[str, int]:
    """Commit a terminal event and its addressed deliveries atomically."""
    from yoke_core.domain import deployment_approval_requests
    from yoke_core.domain.db_helpers import connect

    reason = (
        "Deployment run completed"
        if event_name == "DeploymentRunSucceeded"
        else "Deployment run failed"
    )
    conn = connect()
    try:
        result = deployment_approval_requests.emit_deployment_completion(
            conn,
            run_id=run_id,
            event_name=event_name,
            outcome=outcome,
            reason=reason,
            context=context,
        )
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

__all__ = ["emit_completion"]
