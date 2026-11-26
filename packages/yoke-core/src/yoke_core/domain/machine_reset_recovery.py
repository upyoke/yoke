"""Credential-local recovery of a machine whose cleanup did not prove restoration."""

from datetime import datetime, timedelta

from yoke_contracts.harness_provider_unavailable import (
    PROVIDER_UNAVAILABLE_ERROR_CODE,
    PROVIDER_UNAVAILABLE_RECOVERY,
    probe_stall_retry,
)
from yoke_contracts.machine_qa_failures import HostControlLocalError
from yoke_contracts.timestamps import parse_instant, utc_now
from yoke_core.domain.machine_qa_chain_restore import (
    baseline_receipt,
    failed_baseline_probe,
)
from yoke_core.domain.machine_reset_debt import reset_command

NEEDS_REPAIR = "machine_needs_repair"
#: A reset this soon after a provider-unavailable one skips the stall retry.
STALL_RETRY_SKIP_WINDOW = timedelta(minutes=10)
#: Two provider-unavailable resets this far apart point at the host instead.
ESCALATION_GAP = timedelta(minutes=30)


def prior_provider_unavailable(contract) -> datetime | None:
    """When this debt's previous owed reset read provider-unavailable, if it did."""
    value = getattr(contract, "reset_owed_provider_unavailable_at", None)
    return parse_instant(value) if value else None


def recover_owed_reset(contract, execution, *, now: datetime | None = None):
    baseline = getattr(contract, "reset_owed_baseline", None)
    if baseline is None:
        return None
    prior = prior_provider_unavailable(contract)
    now = now or utc_now()
    retry = prior is None or now - prior > STALL_RETRY_SKIP_WINDOW
    with probe_stall_retry(retry):
        receipt = baseline_receipt(
            baseline, execution.reach_baseline, failure_code=NEEDS_REPAIR
        )
    if not receipt["ok"]:
        code, _, _ = owed_reset_failure(receipt, prior_unavailable_at=prior, now=now)
        receipt["recovery"] = (
            PROVIDER_UNAVAILABLE_RECOVERY
            if code == PROVIDER_UNAVAILABLE_ERROR_CODE
            else reset_command(contract.settings["resource_name"], baseline)
        )
    return receipt


def owed_reset_failure(
    receipt, *, prior_unavailable_at: datetime | None = None, now: datetime | None = None
) -> tuple[str, str, int | None]:
    """Name a failed owed reset: its code, a readable detail, and its exit code.

    Detail and exit code come from the top-level reason, then the nested
    user-equivalence reason, then the last failed probe row, since Windows
    and shell-preconfigured resets nest their probe evidence.
    """
    code = NEEDS_REPAIR
    if receipt.get("error_code") == PROVIDER_UNAVAILABLE_ERROR_CODE:
        escalated = prior_unavailable_at is not None and (
            (now or utc_now()) - prior_unavailable_at > ESCALATION_GAP
        )
        code = NEEDS_REPAIR if escalated else PROVIDER_UNAVAILABLE_ERROR_CODE
    evidence = receipt.get("evidence") or {}
    layers = [evidence, evidence.get("reset") or {}]
    layers += [layer.get("user_equivalence") or {} for layer in list(layers)]
    reason = next((str(each["reason"]) for each in layers if each.get("reason")), "")
    exit_code = next(
        (each["exit_code"] for each in layers if each.get("exit_code") is not None),
        None,
    )
    probe = next((row for each in layers if (row := failed_baseline_probe(each))), None)
    if probe is not None:
        reason = (
            f"{reason} " if reason else ""
        ) + f"(probe {probe.get('name')}: {probe.get('cause')})"
        if exit_code is None:
            exit_code = probe.get("exit_code")
    detail = f"{receipt.get('error_code')}: {reason or receipt.get('diagnostic') or ''}"
    return code, detail, exit_code


class MachineResetFailed(HostControlLocalError):
    """An owed reset failed before the case touched its host."""


def owed_reset_refusal(contract, receipt, *, consequence: str, secrets=()):
    """The refusal a failed owed reset raises, or None when it verified."""
    if receipt is None or receipt["ok"]:
        return None
    code, detail, exit_code = owed_reset_failure(
        receipt, prior_unavailable_at=prior_provider_unavailable(contract)
    )
    evidence = receipt.get("evidence") or {}
    return MachineResetFailed(
        code=code,
        phase="owed_reset",
        detail=f"The owed host reset failed; {consequence}: {detail}",
        exit_code=exit_code,
        stdout=evidence.get("stdout", ""),
        stderr=evidence.get("stderr", ""),
        secrets=secrets,
        recovery_hint=receipt["recovery"],
    )


def unstarted_reset_failure(
    case, test_machine, reset, *, error_code="starting_state_reset_failed"
):
    from yoke_core.domain.machine_qa_case_result import MachineCaseResult

    return MachineCaseResult(
        case_outcome="blocked_on_precondition",
        verdict="blocked",
        evidence={
            "runner_id": "host_control",
            "test_machine": test_machine,
            "baseline": case.host_baseline
            if case.starting_state == "baseline"
            else None,
            "case_started": False,
            "starting_state_reset": reset,
        },
        error_code=error_code,
    )
