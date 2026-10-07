"""Record the inheriting followers of a chain whose case stopped the plan."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from yoke_core.domain.qa_plan_case_chain import ends_chain
from yoke_core.domain.qa_plan_execution_result_state import plan_order


def block_chain_followers(
    requirements: Sequence[Mapping[str, Any]],
    ordinal: int,
    *,
    execution_id: str,
    actor: Any,
    machine_options: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Mark each case that inherits the stopped case's machine as blocked.

    A failed case stops the plan, but the cases chained behind it would
    otherwise be left with no result at all. Each one is begun so the server
    records it blocked, naming the predecessor that did not pass; none of
    them touches the machine.
    """
    from yoke_core.domain.machine_qa_plan_case_execution import (
        execute_plan_machine_case,
    )

    blocked: list[dict[str, Any]] = []
    while not ends_chain(requirements, ordinal):
        ordinal += 1
        follower = requirements[ordinal]
        result = execute_plan_machine_case(
            follower,
            execution_id=execution_id,
            ordinal=ordinal,
            actor=actor,
            **machine_options,
        )
        blocked.append({**plan_order(follower), **result})
    return blocked


__all__ = ["block_chain_followers"]
