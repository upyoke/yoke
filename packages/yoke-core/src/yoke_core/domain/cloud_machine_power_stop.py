"""Stop a cloud Test Machine when its last lease is released.

A call whose lease release leaves a cloud host free names it on its response
(``cloud_machine_release_notice``); the calling client's transport then runs
:func:`stop_released`. The stop holds the host's own lease while it checks and
stops, so a concurrent acquirer queues behind it and then finds the host
stopping, which its start waits out. A host someone else holds keeps running.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextvars import ContextVar

from yoke_contracts.machine_qa_failures import HostControlLocalError
from yoke_contracts.refusal_recovery import compose_refusal
from yoke_core.domain.deploy_remote import CommandRunner
from yoke_core.domain.ec2_instance_power import (
    Ec2InstancePowerError,
    has_elastic_ip,
    instance_state,
    stop_instance,
)
from yoke_core.domain import cloud_machine_power as power

# Set while stop_released runs, so releasing its own hold does not re-enter it.
_stopping: ContextVar[bool] = ContextVar("cloud_machine_power_stopping", default=False)


def _stop_if_running(
    runner: CommandRunner,
    project: str,
    settings: Mapping[str, str],
    aws_env: dict[str, str],
    emit: Callable[[str], None],
) -> None:
    name = settings["resource_name"]
    instance_id = settings["cloud_instance_id"]
    try:
        if instance_state(runner, instance_id, aws_env) not in ("pending", "running"):
            return
        if not has_elastic_ip(runner, instance_id, aws_env):
            emit(
                compose_refusal(
                    f"test_machine_power_stop_skipped: idle Test Machine {name} "
                    f"({instance_id}) has no Elastic IP, so a stop would change "
                    f"the public address its registered host {settings['host']} "
                    "names; it stays running",
                    recovery="declare an Elastic IP for the instance in the "
                    "project's infrastructure; its next lease release stops it",
                )
            )
            return
        emit(f"  Test Machine {name} has no lease")
        stop_instance(runner, instance_id, aws_env, emit)
    except Ec2InstancePowerError as exc:
        emit(
            compose_refusal(
                f"test_machine_power_stop_failed: idle Test Machine {name} "
                f"is still running: {exc}",
                recovery="fix the named cause; its next lease release retries, or "
                f"run `yoke aws exec --project {project} -- ec2 stop-instances "
                f"--instance-ids {instance_id}`",
            )
        )


def _hold_free_host(project: str, name: str) -> int | None:
    """Take the host's own lease if no one holds it; never join its line."""
    response = power._dispatch(
        "claims.coordination_claim.acquire_if_free",
        {
            "project_id": project,
            "key": f"QA_HOST:{name}",
            "reason": "stop the cloud Test Machine its last lease released",
        },
    )
    if response.success:
        return int(response.result["claim"]["id"])
    error = response.error
    if error is not None and error.code in ("claim_held", "claim_stale_holder"):
        return None  # a new lease or a waiter's turn holds it: keep it running
    raise power._refused(
        "test_machine_power_hold_failed",
        f"Test Machine {name} could not be held for its stop "
        f"({error.code if error else 'unknown'}: {error.message if error else ''})",
        "run the Yoke CLI release that the server serves, or update the "
        "server; the machine's next lease release retries the stop",
    )


def stop_released(
    machines: list[Mapping[str, str]],
    *,
    runner: CommandRunner | None = None,
    emit: Callable[[str], None] = power._emit,
) -> None:
    """Stop cloud Test Machines a call's lease release left free.

    The response of any call whose release freed a cloud host names it, and
    the calling client runs this. The stop holds the host's own lease, so a
    concurrent acquirer queues behind it and then finds the host stopping;
    a host someone else holds keeps running. A failure is printed as a named
    refusal and never replaces the call's own result.
    """
    if _stopping.get():
        return  # releasing this stop's own hold names the host again
    token = _stopping.set(True)
    try:
        for machine in machines:
            _stop_one(str(machine["project"]), str(machine["test_machine"]), runner, emit)
    finally:
        _stopping.reset(token)


def _stop_one(
    project: str,
    name: str,
    runner: CommandRunner | None,
    emit: Callable[[str], None],
) -> None:
    try:
        claim_id = _hold_free_host(project, name)
        if claim_id is None:
            return
        try:
            settings = power._call(
                "test_machine.get", {"project": project, "test_machine": name}
            )["settings"]
            if settings.get("cloud_instance_id"):
                _stop_if_running(
                    runner or CommandRunner(), project, settings, power._aws_env(project), emit
                )
        finally:
            power._dispatch(
                "claims.coordination_claim.release",
                {"claim_id": claim_id, "reason": "cloud Test Machine stop settled"},
            )
    except HostControlLocalError as exc:
        emit(compose_refusal(f"{exc.code}: {exc}", recovery=exc.recovery_hint))
    except Exception as exc:  # noqa: BLE001 - a stop never masks its call
        emit(
            compose_refusal(
                f"test_machine_power_stop_failed: Test Machine {name} may still "
                f"be running ({type(exc).__name__}: {exc})",
                recovery=f"run `yoke test-machine verify --project {project} "
                f"--test-machine {name}`, whose release stops it",
            )
        )


__all__ = ["stop_released"]
