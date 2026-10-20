"""Typed server-issued contracts for credential-local Machine QA execution."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from yoke_contracts.machine_qa_case_contract import MachineQaCaseContract
from yoke_contracts.machine_config.test_machine import (
    validate_golden_baseline_path,
    validate_test_machine_settings,
)
from yoke_contracts.machine_qa_case_target import (
    MachineQaCaseTargetError,
)


from yoke_contracts.qa_case_starting_state import (
    reset_baselines,
)
from yoke_contracts.machine_qa_host_control import (
    HOST_CONTROL_PROTOCOL,
    HOST_TEST_COMMAND,
    GUI_SESSION_CONTEXT,
    AGENT_MISSION_ARTIFACT_LIMIT,
    REQUIRED_SESSION_CONTEXT_FIELD,
    VERIFICATION_CHECKS,
    HOST_BASELINES,
    HOST_BASELINE_END_STATE,
    RESET_OPERATION,
    GOLDEN_CAPTURE_OPERATION,
    BRIDGE_DIAGNOSE_OPERATION,
    VERIFY_OPERATION,
    TEST_MACHINE_OPERATIONS,
    HostControlOperation,
)

from yoke_contracts.qa_continuity_fingerprint import (
    execution_protocol,
)


class HostControlExecutionContract(BaseModel):
    """A complete, secret-free operation the local runner may perform."""

    model_config = ConfigDict(extra="forbid")

    protocol: Literal[
        "host-control-v1",
        "host-control-continuity-v1",
        "host-control-reset-recovery-v1",
    ] = HOST_CONTROL_PROTOCOL
    operation: HostControlOperation
    lease_id: int = Field(ge=1)
    lease_key: str
    project_id: int = Field(ge=1)
    project: str
    settings: dict[str, str]
    selection_reason: str | None = None
    reset_owed_baseline: Literal["fresh-host", "shell-preconfigured"] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    checks: list[str] = Field(default_factory=list)
    baselines: list[str] = Field(default_factory=list)
    cases: list[MachineQaCaseContract] = Field(default_factory=list)
    golden_destination: str | None = None
    plan_execution_id: str | None = None
    continues_execution_id: str | None = None
    roster_digest: str | None = None
    ordinal: int | None = Field(default=None, ge=0)
    case_position: int | None = Field(default=None, ge=1)
    baseline_position: int | None = Field(default=None, ge=1)
    contract_digest: str

    @model_validator(mode="after")
    def _registered_shape(self) -> "HostControlExecutionContract":
        self.settings = validate_test_machine_settings(dict(self.settings))
        if self.operation == "verify":
            if self.cases:
                raise ValueError("verification contracts cannot contain cases")
            if self.checks != list(VERIFICATION_CHECKS):
                raise ValueError("verification contract names unknown checks")
            if self.baselines != list(HOST_BASELINES):
                raise ValueError("verification contract names unknown baselines")
        elif self.operation == RESET_OPERATION:
            if self.cases or self.checks:
                raise ValueError("reset contracts carry one baseline and nothing else")
            if len(self.baselines) != 1 or self.baselines[0] not in (HOST_BASELINES):
                raise ValueError("reset contract names one registered baseline")
        elif self.operation in TEST_MACHINE_OPERATIONS:
            if self.cases or self.checks or self.baselines:
                raise ValueError(
                    f"{self.operation} contracts carry no cases, checks, or baselines"
                )
        else:
            if len(self.cases) != 1:
                raise ValueError("case contracts require exactly one case")
            if self.checks:
                raise ValueError("case contracts cannot contain checks")
            if self.baselines != reset_baselines(
                self.cases[0], continues=bool(self.continues_execution_id)
            ):
                raise ValueError("case contract baseline does not match its case")
        if (self.golden_destination is None) == (
            self.operation == GOLDEN_CAPTURE_OPERATION
        ):
            raise ValueError(
                "a golden destination belongs to a golden-capture contract and "
                "to no other operation"
            )
        if self.golden_destination is not None:
            self.golden_destination = validate_golden_baseline_path(
                self.golden_destination
            )
        plan_fields = (
            self.plan_execution_id,
            self.roster_digest,
            self.ordinal,
            self.case_position,
            self.baseline_position,
        )
        if self.operation == "plan_case":
            if any(value is None for value in plan_fields):
                raise ValueError(
                    "plan-case contracts require complete plan cursor context"
                )
            case = self.cases[0]
            if (
                case.case_position != self.case_position
                or case.baseline_position != self.baseline_position
            ):
                raise ValueError("plan-case contract positions do not match its case")
        elif (
            any(value is not None for value in plan_fields)
            or self.continues_execution_id
        ):
            raise ValueError(
                "non-plan host-control contracts cannot name plan cursor context"
            )
        for case in self.cases:
            if case.project_id != self.project_id or case.project != self.project:
                raise ValueError("case project does not match execution project")
        expected_protocol = (
            "host-control-reset-recovery-v1"
            if self.reset_owed_baseline
            else execution_protocol(self.cases)
        )
        if self.protocol != expected_protocol:
            raise ValueError(
                "continuity_runner_required: upgrade the CLI and reissue the continuity contract"
            )
        expected = execution_contract_digest(self)
        if not hmac.compare_digest(self.contract_digest, expected):
            raise ValueError("host-control execution contract digest is invalid")
        return self


def execution_contract_digest(
    contract: HostControlExecutionContract,
) -> str:
    """Return the canonical digest binding every server-issued field."""
    encoded = json.dumps(
        contract.model_dump(
            mode="json", exclude={"contract_digest", "selection_reason"}
        ),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validated_case(case: dict[str, Any]) -> MachineQaCaseContract:
    try:
        return MachineQaCaseContract.model_validate(case)
    except ValidationError as exc:
        raise MachineQaCaseTargetError(
            "; ".join(
                str(error.get("msg") or "").removeprefix("Value error, ")
                for error in exc.errors()
            )
        ) from None


def issue_execution_contract(
    *,
    operation: HostControlOperation,
    lease_id: int,
    lease_key: str,
    project_id: int,
    project: str,
    settings: dict[str, str],
    selection_reason: str | None = None,
    reset_owed_baseline: str | None = None,
    checks: list[str] | None = None,
    baselines: list[str] | None = None,
    cases: list[dict[str, Any]] | None = None,
    golden_destination: str | None = None,
    plan_execution_id: str | None = None,
    continues_execution_id: str | None = None,
    roster_digest: str | None = None,
    ordinal: int | None = None,
    case_position: int | None = None,
    baseline_position: int | None = None,
) -> HostControlExecutionContract:
    """Build and digest one normalized server-authoritative contract."""
    normalized_cases = [_validated_case(case) for case in (cases or [])]
    provisional = HostControlExecutionContract.model_construct(
        protocol=(
            "host-control-reset-recovery-v1"
            if reset_owed_baseline
            else execution_protocol(normalized_cases)
        ),
        reset_owed_baseline=reset_owed_baseline,
        operation=operation,
        lease_id=int(lease_id),
        lease_key=str(lease_key),
        project_id=int(project_id),
        project=str(project),
        settings=validate_test_machine_settings(dict(settings)),
        selection_reason=selection_reason,
        checks=list(checks or []),
        baselines=list(baselines or []),
        cases=normalized_cases,
        golden_destination=golden_destination,
        plan_execution_id=plan_execution_id,
        continues_execution_id=continues_execution_id,
        roster_digest=roster_digest,
        ordinal=ordinal,
        case_position=case_position,
        baseline_position=baseline_position,
        contract_digest="",
    )
    return HostControlExecutionContract.model_validate(
        {
            **provisional.model_dump(mode="json"),
            "contract_digest": execution_contract_digest(provisional),
        }
    )


__all__ = [
    "AGENT_MISSION_ARTIFACT_LIMIT",
    "BRIDGE_DIAGNOSE_OPERATION",
    "GOLDEN_CAPTURE_OPERATION",
    "GUI_SESSION_CONTEXT",
    "HOST_BASELINE_END_STATE",
    "HOST_CONTROL_PROTOCOL",
    "HOST_TEST_COMMAND",
    "HostControlExecutionContract",
    "HostControlOperation",
    "MachineQaCaseContract",
    "REQUIRED_SESSION_CONTEXT_FIELD",
    "RESET_OPERATION",
    "TEST_MACHINE_OPERATIONS",
    "HOST_BASELINES",
    "VERIFICATION_CHECKS",
    "VERIFY_OPERATION",
    "execution_contract_digest",
    "issue_execution_contract",
]
