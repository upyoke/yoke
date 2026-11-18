"""Hold a host command's lease before starting its cloud machine.

Desktop access, browser sign-in and ``yoke test-machine exec`` share this one
lease-then-power-on path; cloud machines stay running after release.
"""

from contextlib import contextmanager

from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.machine_qa_failures import host_control_failure
from yoke_cli.transport.dispatcher import call_dispatcher
from yoke_cli.commands.adapters.test_machine_operation import _power


def _call(function, payload, actor):
    response = call_dispatcher(
        function_id=function,
        target=TargetRef(kind="global"),
        payload=payload,
        actor=actor,
    )
    if response.success:
        return response.result
    error = response.error
    raise RuntimeError(
        f"{error.code}: {error.message}. "
        + (
            error.recovery_hint
            or "Inspect the machine's lease and retry after its holder finishes."
        )
    )


@contextmanager
def desktop_lease(
    *,
    project,
    test_machine,
    settings,
    actor,
    reason,
    detail=None,
    operator_access=None,
):
    """Borrow the caller's lease or an authorized assist; release only our own."""
    claim_id = None
    if not operator_access:
        if detail is None:
            detail = _call(
                "test_machine.get",
                {"project": project, "test_machine": test_machine},
                actor,
            )
        lease = detail.get("active_lease")
        if lease and lease["session_id"] != actor.session_id:
            raise RuntimeError(
                f"test_machine_leased: test machine {test_machine} is leased by session "
                f"{lease['session_id']}. Wait for its lease to release or ask its holder to finish."
            )
        if not lease:
            claim_id = _call(
                "claims.coordination_claim.acquire_if_free",
                {
                    "project_id": project,
                    "key": f"QA_HOST:{test_machine}",
                    "reason": reason,
                },
                actor,
            )["claim"]["id"]
    try:
        try:
            _power().power_on(project, settings)
        except Exception as exc:
            code, message, recovery = host_control_failure(exc, phase="lease_power_on")
            raise RuntimeError(f"{code}: {message}. {recovery}") from exc
        yield
    finally:
        if claim_id is not None:
            _call(
                "claims.coordination_claim.release",
                {"claim_id": claim_id, "reason": f"finished: {reason}"},
                actor,
            )
