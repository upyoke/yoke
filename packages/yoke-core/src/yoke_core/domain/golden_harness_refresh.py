"""Refresh a Test Machine golden to the latest harness CLIs before QA resets to it.

The first machine case a QA plan resets on each Test Machine compares the
harness CLI versions recorded beside that host's golden with each CLI's latest
published release. A golden that is behind is refreshed once, under the plan's
own host lease: reset to the golden, install the newer CLIs as the test user,
then capture a new golden through the ordinary golden-capture operation, which
keeps sign-ins, keychains and browser cookies out of it. The case then begins
again, so its reset and every later one restore the refreshed golden. A golden
already current costs one record read and no reset, install or capture.
"""

from __future__ import annotations

import json
import urllib.request
from typing import Any, Callable, Mapping

from yoke_contracts.api.function_call import ActorContext, TargetRef
from yoke_contracts.harness_cli_releases import (
    HARNESS_CLI_RELEASES,
    outdated_harness_clis,
)
from yoke_contracts.machine_qa_execution import HostControlExecutionContract
from yoke_contracts.machine_qa_failures import HostControlLocalError

LATEST_FETCH_TIMEOUT_SECONDS = 30
REFRESH_RECOVERY_SUFFIX = (
    " The plan stopped before its case reset so no QA ran on stale CLIs; "
    "repair the named step and rerun the QA plan."
)

# (plan execution id, machine) pairs already checked by this process.
_checked: set[tuple[str, str]] = set()


def fetch_release_channel(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "yoke-golden-refresh"})
    with urllib.request.urlopen(request, timeout=LATEST_FETCH_TIMEOUT_SECONDS) as reply:
        return reply.read().decode("utf-8")


def _refused(code: str, detail: str, recovery: str) -> Exception:
    from yoke_core.domain.machine_qa_plan_case_execution import (
        MachinePlanCaseDispatchError,
    )

    return MachinePlanCaseDispatchError(
        f"golden refresh stopped: {detail}",
        error_code=code,
        recovery_hint=recovery + REFRESH_RECOVERY_SUFFIX,
    )


def latest_harness_cli_versions(fetch: Callable[[str], str]) -> dict[str, str]:
    """Return each harness id's latest published CLI version, or refuse."""
    latest = {}
    for release in HARNESS_CLI_RELEASES:
        try:
            latest[release.harness_id] = release.latest_version(
                fetch(release.latest_url)
            )
        except Exception as error:
            raise _refused(
                "golden_refresh_latest_unavailable",
                f"{release.latest_url} did not answer with a {release.harness_id} "
                f"release ({type(error).__name__}: {error})",
                "Restore this workstation's HTTPS access to the release channel.",
            ) from error
    return latest


def refreshed_case_contract(
    raw_contract: Mapping[str, Any],
    *,
    plan_execution_id: str,
    actor: ActorContext,
    begin: Callable[[], Mapping[str, Any]],
    fetch: Callable[[str], str] = fetch_release_channel,
) -> dict[str, Any]:
    """Return the case contract to run, refreshing its host's golden first."""
    settings = raw_contract.get("settings") or {}
    key = (plan_execution_id, str(settings.get("resource_name")))
    golden = settings.get("golden_baseline_path")
    if not raw_contract.get("baselines") or not golden or key in _checked:
        return dict(raw_contract)
    contract = HostControlExecutionContract.model_validate(dict(raw_contract))
    from yoke_core.domain.host_control_runner import resolve_contract_host_control
    from yoke_core.domain.machine_qa_host_control import (
        register_test_machine_host_control,
    )
    from yoke_harness.golden_harness_clis import (
        install_harness_clis,
        read_golden_harness_clis,
    )

    latest = latest_harness_cli_versions(fetch)
    machine = key[1]
    step = "record read"
    try:
        register_test_machine_host_control()
        control, _material = resolve_contract_host_control(
            {
                "project_id": contract.project_id,
                "project": contract.project,
                "settings": contract.settings,
            }
        )
        recorded = read_golden_harness_clis(control, golden)
        outdated = outdated_harness_clis(recorded, latest)
        if not outdated:
            _checked.add(key)
            return dict(raw_contract)
        for step, run in (
            ("reset", control.reset_installer_test_host),
            ("install", lambda: install_harness_clis(control, latest, outdated)),
        ):
            result = run()
            if not result.ok:
                raise _refused(
                    f"golden_refresh_{step}_failed",
                    f"{step} on {machine} failed ({result.error_code}): "
                    + json.dumps(result.evidence, default=str)[:800],
                    str(
                        result.evidence.get("recovery")
                        or f"Repair the {step} on {machine}."
                    ),
                )
    except (HostControlLocalError, RuntimeError, ValueError, OSError) as error:
        if getattr(error, "error_code", None):
            raise
        raise _refused(
            "golden_refresh_host_failed",
            f"{step} on {machine} raised {type(error).__name__}: {error}",
            f"Restore SSH access and /usr/bin/python3 on {machine}.",
        ) from error
    _capture_golden(contract, plan_execution_id=plan_execution_id, actor=actor)
    _checked.add(key)
    begun = begin()
    if begun.get("state") != "ready" or not isinstance(begun.get("execution"), dict):
        raise _refused(
            "golden_refresh_case_not_ready",
            f"the case did not begin again after the refresh ({begun.get('state')})",
            "The refreshed golden is registered.",
        )
    return dict(begun["execution"])


def _capture_golden(
    contract: HostControlExecutionContract,
    *,
    plan_execution_id: str,
    actor: ActorContext,
) -> None:
    """Capture and register the new golden under the plan's own host lease."""
    from yoke_core.domain.machine_qa_local_execution import (
        execute_host_operation_contract,
    )
    from yoke_core.domain.qa_plan_execution_checkin import (
        QaPlanCommunicationUnknown,
        deliver_plan_function,
    )
    from yoke_core.domain.qa_plan_execution_result_state import QaPlanExecutionError
    from yoke_harness.golden_snapshot_retention import (
        SnapshotRetentionError,
        retain_after_verified_capture,
    )

    machine = str(contract.settings["resource_name"])
    shape = {
        "project": contract.project,
        "operation": "golden_capture",
        "plan_execution_id": plan_execution_id,
    }

    def call(function_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return deliver_plan_function(
            function_id=function_id,
            target=TargetRef(kind="global"),
            payload=payload,
            actor=actor,
        )

    try:
        execution = call("test_machine.operation.begin", {**shape, "machine": machine})[
            "execution"
        ]
        echo = {**shape, "destination": execution.get("golden_destination")}
        try:
            submission = execute_host_operation_contract(execution)
        except Exception:
            call(
                "test_machine.operation.abort",
                {
                    **echo,
                    "lease_id": execution["lease_id"],
                    "contract_digest": execution["contract_digest"],
                    "reason": "local_execution_failed",
                },
            )
            raise
        submitted = call(
            "test_machine.operation.submit", {**echo, **submission.payload}
        )
    except QaPlanCommunicationUnknown:
        raise
    except (QaPlanExecutionError, RuntimeError, ValueError) as error:
        raise _refused(
            "golden_refresh_capture_failed",
            f"golden capture on {machine} did not complete: {error}",
            "Read the named refusal; a project admin can capture by hand with "
            f"`yoke test-machine golden-capture --project {contract.project} "
            f"--machine {machine}`.",
        ) from error
    if submitted.get("status") != "verified":
        raise _refused(
            "golden_refresh_capture_failed",
            f"golden capture on {machine} reported {submitted.get('error_code')}: "
            f"{submitted.get('checks')}",
            "Repair the failed capture check named in the receipt.",
        )
    try:
        retain_after_verified_capture("golden_capture", True, submitted, execution)
    except SnapshotRetentionError as error:
        raise _refused(error.code, error.detail, error.recovery) from error


__all__ = [
    "fetch_release_channel",
    "latest_harness_cli_versions",
    "refreshed_case_contract",
]
