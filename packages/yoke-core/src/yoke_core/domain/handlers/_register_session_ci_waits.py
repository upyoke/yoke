"""Register the gate-side pending-CI-wait write.

``adapter_status='internal'`` because no agent types this: the gates that
dispatch CI call it for themselves the moment a run id exists. It is
session-required rather than claim-required, because the session is the
whole subject of the row — the run's verdict is owed to whoever dispatched
it, claim or no claim.
"""

from __future__ import annotations

from yoke_core.domain.handlers import session_ci_wait_writes as _waits

_MODULE = "yoke_core.domain.handlers.session_ci_wait_writes"


def register(registry) -> None:
    registry.register(
        "session_ci_wait.record",
        _waits.handle_record_ci_wait,
        _waits.RecordCiWaitRequest,
        _waits.RecordCiWaitResponse,
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


__all__ = ["register"]
