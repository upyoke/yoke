"""Read fleet rehearsal coverage from the environment that owns it.

One reader for every release gate, so a gate running on a hosted runner over
HTTPS and a gate running beside a local database cannot disagree about what
was rehearsed: the function id is the same on both, and the active connection
alone decides whether the call is dispatched in process or relayed.

Reads are refused rather than emptied. An unreadable store and an unrehearsed
build are different facts, and the caller that cannot tell them apart is the
one that ships an unrehearsed build.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Sequence, Tuple

from yoke_contracts.api.function_call import TargetRef

COVERAGE_FUNCTION_ID = "projects.environment_settings.get"

#: The gate reads leaves it names; the settings surface refuses container
#: projections, so an unexpected container is a read failure, not coverage.
_MISSING_VALUES = "coverage read returned no values"


def read_coverage(
    *, project: str, environment: str, paths: Sequence[str]
) -> Tuple[Dict[str, Any], str]:
    """Coverage leaves for one environment, or why they could not be read."""
    from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
    from yoke_core.domain.migration_preflight_receipt import (
        target_environment_for_admin_env,
    )

    wanted = [str(path).strip() for path in paths if str(path or "").strip()]
    if not wanted:
        # Nothing to ask about is not the same as nothing being covered, and a
        # request with no paths is refused by the settings surface anyway.
        return {}, ""
    try:
        response = call_dispatcher(
            function_id=COVERAGE_FUNCTION_ID,
            target=TargetRef(kind="global"),
            payload={
                "project": project,
                "environment": target_environment_for_admin_env(environment),
                "paths": wanted,
            },
        )
    except Exception as exc:  # noqa: BLE001 - unreadable evidence fails closed
        return {}, str(exc)
    if not response.success:
        detail = (
            response.error.message
            if response.error is not None
            else "coverage read refused"
        )
        return {}, detail
    result = response.result if isinstance(response.result, Mapping) else {}
    values = result.get("values")
    if not isinstance(values, Mapping):
        return {}, _MISSING_VALUES
    return dict(values), ""


__all__ = ["COVERAGE_FUNCTION_ID", "read_coverage"]
