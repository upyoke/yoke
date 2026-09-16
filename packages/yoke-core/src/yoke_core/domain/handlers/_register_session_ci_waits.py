"""Register the gate-side pending-CI-wait writes.

``adapter_status='internal'`` because no agent types these: the gates that
dispatch CI call ``record`` the moment a run id exists, and the watcher
that received success or failure calls ``resolve`` so the sweep does not
wake that session for a verdict it already printed. Both are
session-required rather than claim-required, because the session is the
whole subject of the row.
"""

from __future__ import annotations

from yoke_core.domain.handlers import session_ci_wait_writes as _waits

_MODULE = "yoke_core.domain.handlers.session_ci_wait_writes"

_SHARED = dict(
    stability="stable",
    owner_module=_MODULE,
    target_kinds=["global"],
    side_effects=["session_ci_run_wait_write"],
    emitted_event_names=["YokeFunctionCalled"],
    guardrails=["session_required"],
    adapter_status="internal",
    claim_required_kind=None,
    ambient_session_required=True,
)


def register(registry) -> None:
    registry.register(
        "session_ci_wait.record",
        _waits.handle_record_ci_wait,
        _waits.RecordCiWaitRequest,
        _waits.RecordCiWaitResponse,
        **_SHARED,
    )
    registry.register(
        "session_ci_wait.resolve",
        _waits.handle_resolve_ci_wait,
        _waits.ResolveCiWaitRequest,
        _waits.ResolveCiWaitResponse,
        **_SHARED,
    )


__all__ = ["register"]
