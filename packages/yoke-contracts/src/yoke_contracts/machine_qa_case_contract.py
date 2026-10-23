"""Immutable, validated snapshots for credential-local Machine QA cases."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from yoke_contracts.machine_qa_case_target import require_case_execution_target
from yoke_contracts.qa_case_starting_state import require_materialized_starting_state
from yoke_contracts.qa_continuity_fingerprint import require_continuity_state


class MachineQaCaseContract(BaseModel):
    """Immutable database snapshot needed to execute and persist one case."""

    model_config = ConfigDict(extra="forbid")

    requirement_id: int = Field(ge=1)
    public_ref: str | None = None
    deployment_run_id: str | None = None
    standalone_execution_id: str | None = Field(default=None, min_length=1)
    deployment_stage: str | None = None
    deployment_member_public_ref: str | None = None
    plan_id: int | None
    case_key: str
    method_id: str
    method_name: str
    runner_id: Literal["host_control", "agent_mission", "worktree_run"]
    required_capability_kinds: list[str]
    verdict_path: str
    qa_kind: str
    instructions: str
    expected_outcome: str
    method_config: dict[str, Any]
    host_baseline: str | None
    starting_state: Literal["baseline", "inherit", "as_is"] | None = None
    starting_state_reason: str | None = None
    #: False only while the next case of the same plan run inherits this
    #: case's machine; the runner restores the chain's starting state after
    #: a case that ends its chain, or after one that did not pass.
    ends_chain: bool = True
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
        if (
            sum(
                value is not None
                for value in (
                    self.public_ref,
                    self.deployment_run_id,
                    self.standalone_execution_id,
                )
            )
            != 1
        ):
            raise ValueError(
                "Machine QA case requires one item, deployment-run, or standalone subject"
            )
        if self.deployment_run_id is None and (
            self.deployment_stage is not None
            or self.deployment_member_public_ref is not None
        ):
            raise ValueError(
                "non-deployment Machine QA cases cannot name deployment scope"
            )
        if self.standalone_execution_id is not None and self.plan_id is None:
            raise ValueError("standalone Machine QA cases require a saved plan")
        if self.deployment_member_public_ref is not None and not self.deployment_stage:
            raise ValueError(
                "deployment member Machine QA cases require a deployment stage"
            )
        encoded_target = json.dumps(
            self.execution_target,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        expected_digest = hashlib.sha256(encoded_target).hexdigest()
        if not hmac.compare_digest(self.execution_target_digest, expected_digest):
            raise ValueError("Machine QA execution target digest is invalid")
        require_case_execution_target(self)
        if self.runner_id == "worktree_run":
            if not self.method_config.get("test_machine"):
                raise ValueError(
                    "Command host admission requires method_config.test_machine"
                )
        else:
            require_materialized_starting_state(self)
        require_continuity_state(self)
        return self
