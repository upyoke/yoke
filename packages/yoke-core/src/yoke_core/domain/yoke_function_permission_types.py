"""The dispatcher's permission-decision shape.

Its own module because both the shared routing path
(:mod:`yoke_core.domain.yoke_function_permissions`) and the per-function
resolvers it delegates to
(:mod:`yoke_core.domain.yoke_function_permissions_by_function`) return
this type; defining it in either would make the pair import each other.
"""

from __future__ import annotations

from dataclasses import dataclass

from yoke_contracts.api.function_call import FunctionCallResponse


@dataclass(frozen=True)
class DispatchPermission:
    """One authorization answer for one dispatched call.

    ``error`` carries the populated refusal response when the call is
    denied; the resolved project and permission ride along either way so
    dispatcher telemetry records what was checked, not just the verdict.
    """

    permission_key: str | None
    project_id: int | None
    project_slug: str | None
    visible_project_ids: tuple[int, ...] | None = None
    error: FunctionCallResponse | None = None


__all__ = ["DispatchPermission"]
