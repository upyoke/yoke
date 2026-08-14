"""Machine QA case outcomes and structured coordination-wait evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from yoke_core.domain.coordination_lease_contention import (
    LeaseContention,
    waiting_lease_evidence,
)
from yoke_core.domain.coordination_leases import Lease
from yoke_core.domain.machine_qa_method_contracts import MachineQaExecutionError


@dataclass(frozen=True)
class MachineCaseResult:
    case_outcome: str
    verdict: str
    evidence: dict[str, Any]
    capture_degraded_reason: str | None = None
    error_code: str | None = None


class MachineQaLeaseHeld(MachineQaExecutionError):
    """The test machine is in use and this case must remain waiting."""

    def __init__(
        self,
        *,
        lease: Lease,
        machine: str,
        contention: LeaseContention | None = None,
    ) -> None:
        super().__init__(f"test machine {machine!r} is in use by another execution")
        self.lease = lease
        self.machine = machine
        self.contention = contention

    def waiting_result(self) -> MachineCaseResult:
        return MachineCaseResult(
            case_outcome="waiting",
            verdict="waiting",
            evidence={
                "runner_id": "host_control",
                "machine": self.machine,
                "case_started": False,
                "lease": waiting_lease_evidence(self.lease, self.contention),
            },
        )


__all__ = ["MachineCaseResult", "MachineQaLeaseHeld"]
