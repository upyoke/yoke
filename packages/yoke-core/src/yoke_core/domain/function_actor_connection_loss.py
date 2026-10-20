"""Name a failed database identity lookup before authorization runs."""

from yoke_core.domain import db_backend


def name_identity_connection_loss(function):
    from functools import wraps

    @wraps(function)
    def bind(entry, request, **kwargs):
        from yoke_core.domain.yoke_function_actor_identity import (
            BoundIdentity,
            _error_response,
        )
        from yoke_core.domain.function_connection_loss import connection_lost_outcome
        from yoke_core.domain.connected_env_readiness import (
            is_connection_unavailable_error,
        )

        try:
            return function(entry, request, **kwargs)
        except Exception as exc:
            if not (
                is_connection_unavailable_error(exc)
                or isinstance(exc, db_backend.operational_error_types())
            ):
                raise
            outcome = connection_lost_outcome(entry, exc)
            return BoundIdentity(
                None,
                request.actor.session_id or "",
                kwargs.get("ambient_session_id") or "",
                error=_error_response(
                    request,
                    entry,
                    code=outcome.error.code,
                    message=outcome.error.message + " " + outcome.error.recovery_hint,
                ),
            )

    return bind
