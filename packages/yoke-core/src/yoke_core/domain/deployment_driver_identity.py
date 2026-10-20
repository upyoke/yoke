"""Retain the local driver's resolved identity for one execution only."""

from contextvars import ContextVar
from functools import wraps

_LOOKUPS = ContextVar("deployment_driver_identity", default=None)


def identity_read(key, reader):
    cache = _LOOKUPS.get()
    if cache is None:
        return reader()
    if key not in cache:
        cache[key] = reader()
    return cache[key]


def driver_identity_operation(function):
    @wraps(function)
    def run(run_id, *args, **kwargs):
        from yoke_core.domain.yoke_function_actor_identity import (
            _default_actor_id_resolver,
        )
        from yoke_core.domain.session_ambient_identity import resolve_ambient_session_id
        from yoke_core.domain.session_less_actor_binding import operating_actor_id
        from yoke_core.domain.connected_env_readiness import (
            is_connection_unavailable_error,
        )
        from yoke_core.domain import db_backend
        from yoke_core.domain.deploy_pipeline_unknown_outcome import (
            DeploymentOutcomeUnknown,
        )

        token = _LOOKUPS.set({})
        try:
            session = resolve_ambient_session_id() or ""
            if not session or not _default_actor_id_resolver(session).actor_id:
                operating_actor_id()
            return function(run_id, *args, **kwargs)
        except Exception as exc:
            if not (
                is_connection_unavailable_error(exc)
                or isinstance(exc, db_backend.operational_error_types())
            ):
                raise
            raise DeploymentOutcomeUnknown(
                run_id, "driver actor/database lookup", "", str(exc)
            ) from exc
        finally:
            _LOOKUPS.reset(token)

    return run
