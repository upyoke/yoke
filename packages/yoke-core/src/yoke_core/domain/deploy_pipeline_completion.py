"""Transactional completion events emitted by deployment pipeline outcomes."""

from typing import Any, Mapping


def emit_completion(
    run_id: str,
    event_name: str,
    outcome: str,
    context: Mapping[str, Any],
) -> None:
    """Commit one terminal deployment-run event.

    A defect still raises — an unknown event name, a run id that resolves
    to nothing — because those are the caller getting the call wrong. A
    telemetry drop does not: ``deployment_runs`` already owns the terminal
    outcome by the time the pipeline reaches here, so a filtered severity
    or an events outage is recorded as a warning instead of becoming the
    pipeline's own result.
    """
    from yoke_core.domain import deployment_approval_requests
    from yoke_core.domain.db_helpers import connect

    conn = connect()
    try:
        deployment_approval_requests.emit_deployment_completion(
            conn,
            run_id=run_id,
            event_name=event_name,
            outcome=outcome,
            context=context,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


__all__ = ["emit_completion"]
