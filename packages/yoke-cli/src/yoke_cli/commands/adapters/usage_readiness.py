"""Usage rows for readiness and path-claim flow commands."""

from __future__ import annotations

from typing import Dict

from yoke_cli.commands.adapters.claims_path_flow import (
    CLAIMS_PATH_ACTIVATION_RUN_USAGE,
    CLAIMS_PATH_REQUIRED_GATE_USAGE,
)
from yoke_cli.commands.adapters.readiness import (
    READINESS_CHECK_USAGE,
    READINESS_PRD_VALIDATE_USAGE,
    READINESS_REPAIR_CLAIM_COVERAGE_USAGE,
    READINESS_REPAIR_STALE_COUNT_USAGE,
)


READINESS_USAGE_BY_ID: Dict[str, str] = {
    "claims.path.required_gate": CLAIMS_PATH_REQUIRED_GATE_USAGE,
    "claims.path.activation_run": CLAIMS_PATH_ACTIVATION_RUN_USAGE,
    "readiness.check.run": READINESS_CHECK_USAGE,
    "readiness.prd_validate.run": READINESS_PRD_VALIDATE_USAGE,
    "readiness.repair_stale_count": READINESS_REPAIR_STALE_COUNT_USAGE,
    "readiness.repair_claim_coverage": READINESS_REPAIR_CLAIM_COVERAGE_USAGE,
}


__all__ = ["READINESS_USAGE_BY_ID"]
