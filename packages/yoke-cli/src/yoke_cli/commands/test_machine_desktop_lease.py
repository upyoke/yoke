"""Hold a host command's lease before starting its cloud machine.

Desktop access, browser sign-in and ``yoke test-machine exec`` share this one
lease-then-power-on path; cloud machines stay running after release. A release
onto an empty line leaves this session a short hold-over of the host, which the
command names on stderr; the session's next acquire of the host takes it.
"""

import sys
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
                {"test_machine": test_machine},
                actor,
            )
        lease = detail.get("active_lease")
        if lease and lease["session_id"] != actor.session_id and not holdover_lapsed(lease):
            raise RuntimeError(
                f"test_machine_leased: test machine {test_machine} is leased by session "
                f"{lease['session_id']}. Wait for its lease to release or ask its holder to finish."
            )
        # Taking our own hold-over consumes it, so this command's release
        # renews it instead of letting it lapse mid-command.
        # A lapsed hold-over of another session is released by the acquire.
        if not lease or lease.get("holdover_expires_at"):
            claim_id = _call(
                "test_machine.lease_acquire",
                {"test_machine": test_machine},
                actor,
            )["claim_id"]
    try:
        try:
            if not operator_access:
                power = _power()
                with power.power_dispatch_scope(actor=actor):
                    power.power_on(project, settings)
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
            _report_holdover(test_machine, actor)


def holdover_lapsed(lease):
    """True when *lease* is a hold-over past its expiry (any acquire releases it)."""
    from yoke_contracts.timestamps import parse_instant, utc_now

    expires = (lease or {}).get("holdover_expires_at")
    return bool(expires) and parse_instant(expires) <= utc_now()


def _report_holdover(test_machine, actor):
    """Name the hold-over the release left this session, and when it lapses."""
    lease = (_call("test_machine.get", {"test_machine": test_machine}, actor) or {}).get(
        "active_lease"
    )
    if not lease or lease.get("session_id") != actor.session_id:
        return
    expires = lease.get("holdover_expires_at")
    if expires:
        print(
            f"hold-over: {test_machine} stays held for this session until {expires} "
            f"(lease {lease['id']}). Your next `yoke qa case run`, `yoke qa plan run` "
            "or `yoke test-machine exec` on it takes it; another session queues behind it.",
            file=sys.stderr,
        )
