"""Protect recorded captures from completion writes that bypass agent review."""

from collections.abc import Mapping
from typing import Any

from yoke_contracts.qa_execution_status import CAPTURED
from yoke_contracts.refusal_recovery import compose_refusal
from yoke_core.domain.qa_constants import is_agent_reviewed_case


def captured_completion_refusal(
    run: Mapping[str, Any], payload: Mapping[str, Any], requirement_id: int
) -> str | None:
    """A completed capture owns its evidence; its reviewer owns the verdict."""
    if (
        run["execution_status"] != CAPTURED
        or not is_agent_reviewed_case(run["verdict_path"], run["method_id"])
        or (payload.get("verdict") is None and payload.get("raw_result") is None)
    ):
        return None
    return compose_refusal(
        "qa run complete cannot change the verdict or raw result of an "
        "already captured, agent-reviewed run",
        recovery=(
            "Review the captured evidence with `yoke qa run record-verdict "
            f"--requirement-id {requirement_id} --performed-by agent "
            "--verdict V --verdict-reason TEXT`; preserve its raw result"
        ),
    )
