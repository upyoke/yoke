"""Typed server-issued contracts for credential-local Machine QA execution."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from yoke_contracts.machine_config.test_machine import (
    validate_test_machine_settings,
)


HOST_CONTROL_PROTOCOL = "host-control-v1"
HOST_TEST_COMMAND = "/bin/test"
GUI_SESSION_CONTEXT = "gui"
AGENT_MISSION_ARTIFACT_LIMIT = 100
REQUIRED_SESSION_CONTEXT_FIELD = "required_session_context"
VERIFICATION_CHECKS = ("connection", "terminal_bridge")
VERIFICATION_BASELINES = ("fresh-host", "shell-preconfigured")
HostControlOperation = Literal[
    "verify",
    "case",
    "baseline_group",
    "plan_case",
]


class MachineQaCaseContract(BaseModel):
    """Immutable database snapshot needed to execute and persist one case."""

    model_config = ConfigDict(extra="forbid")

    requirement_id: int = Field(ge=1)
    item_id: int | None = Field(default=None, ge=1)
    deployment_run_id: str | None = None
    plan_id: int | None
    case_key: str
    method_id: str
    method_name: str
    runner_id: Literal["host_control", "agent_mission"]
    required_capability_kinds: list[str]
    verdict_path: str
    qa_kind: str
    instructions: str
    expected_outcome: str
    method_config: dict[str, Any]
    host_baseline: str | None
    entry_surface: str | None
    required_completion: str | None
    workflow_transition_id: str | None
    project_id: int = Field(ge=1)
    project: str
    execution_target: dict[str, Any]
    execution_target_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    lane_branch: str | None
    case_position: int | None = Field(default=None, ge=1)
    baseline_position: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _one_subject(self) -> "MachineQaCaseContract":
        if (self.item_id is None) == (self.deployment_run_id is None):
            raise ValueError(
                "Machine QA case requires one item or deployment-run subject"
            )
        encoded_target = json.dumps(
            self.execution_target,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        expected_digest = hashlib.sha256(encoded_target).hexdigest()
        if not hmac.compare_digest(self.execution_target_digest, expected_digest):
            raise ValueError("Machine QA execution target digest is invalid")
        target_project = self.execution_target.get("project")
        environment = self.execution_target.get("environment")
        tenant = self.execution_target.get("tenant")
        if (
            not isinstance(target_project, dict)
            or int(target_project.get("id") or 0) != self.project_id
            or str(target_project.get("slug") or "") != self.project
            or not isinstance(environment, dict)
            or set(environment) != {"name"}
            or not str(environment.get("name") or "")
            or not isinstance(tenant, dict)
            or not str(tenant.get("slug") or "")
            or not isinstance(self.execution_target.get("endpoints"), dict)
        ):
            raise ValueError(
                "Machine QA execution target does not match its case authority"
            )
        return self


class HostControlExecutionContract(BaseModel):
    """A complete, secret-free operation the local runner may perform."""

    model_config = ConfigDict(extra="forbid")

    protocol: Literal["host-control-v1"] = HOST_CONTROL_PROTOCOL
    operation: HostControlOperation
    lease_id: int = Field(ge=1)
    lease_key: str
    project_id: int = Field(ge=1)
    project: str
    settings: dict[str, str]
    checks: list[str] = Field(default_factory=list)
    baselines: list[str] = Field(default_factory=list)
    cases: list[MachineQaCaseContract] = Field(default_factory=list)
    plan_execution_id: str | None = None
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
            if self.baselines != list(VERIFICATION_BASELINES):
                raise ValueError("verification contract names unknown baselines")
        elif self.operation in {"case", "plan_case"}:
            if len(self.cases) != 1:
                raise ValueError("case contracts require exactly one case")
            if self.checks:
                raise ValueError("case contracts cannot contain checks")
            expected = (
                [self.cases[0].host_baseline] if self.cases[0].host_baseline else []
            )
            if self.baselines != expected:
                raise ValueError("case contract baseline does not match its case")
        elif not self.cases:
            raise ValueError("baseline-group contracts require cases")
        elif len(self.baselines) != 1 or any(
            case.host_baseline != self.baselines[0] for case in self.cases
        ):
            raise ValueError(
                "baseline-group cases must share their registered baseline"
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
        elif any(value is not None for value in plan_fields):
            raise ValueError(
                "non-plan host-control contracts cannot name plan cursor context"
            )
        for case in self.cases:
            if case.project_id != self.project_id or case.project != self.project:
                raise ValueError("case project does not match execution project")
        expected = execution_contract_digest(self)
        if not hmac.compare_digest(self.contract_digest, expected):
            raise ValueError("host-control execution contract digest is invalid")
        return self


def _digest_payload(contract: HostControlExecutionContract) -> dict[str, Any]:
    return contract.model_dump(
        mode="json",
        exclude={"contract_digest"},
    )


def execution_contract_digest(
    contract: HostControlExecutionContract,
) -> str:
    """Return the canonical digest binding every server-issued field."""
    encoded = json.dumps(
        _digest_payload(contract),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def issue_execution_contract(
    *,
    operation: HostControlOperation,
    lease_id: int,
    lease_key: str,
    project_id: int,
    project: str,
    settings: dict[str, str],
    checks: list[str] | None = None,
    baselines: list[str] | None = None,
    cases: list[dict[str, Any]] | None = None,
    plan_execution_id: str | None = None,
    roster_digest: str | None = None,
    ordinal: int | None = None,
    case_position: int | None = None,
    baseline_position: int | None = None,
) -> HostControlExecutionContract:
    """Build and digest one normalized server-authoritative contract."""
    provisional = HostControlExecutionContract.model_construct(
        protocol=HOST_CONTROL_PROTOCOL,
        operation=operation,
        lease_id=int(lease_id),
        lease_key=str(lease_key),
        project_id=int(project_id),
        project=str(project),
        settings=validate_test_machine_settings(dict(settings)),
        checks=list(checks or []),
        baselines=list(baselines or []),
        cases=[MachineQaCaseContract.model_validate(case) for case in (cases or [])],
        plan_execution_id=plan_execution_id,
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
    "GUI_SESSION_CONTEXT",
    "HOST_CONTROL_PROTOCOL",
    "HOST_TEST_COMMAND",
    "HostControlExecutionContract",
    "HostControlOperation",
    "MachineQaCaseContract",
    "REQUIRED_SESSION_CONTEXT_FIELD",
    "VERIFICATION_BASELINES",
    "VERIFICATION_CHECKS",
    "execution_contract_digest",
    "issue_execution_contract",
]
