"""Where a gated stage sits in its flow, so its effect is not overstated.

Not every human-approval stage precedes a deploy. A sign-off at the end of a
flow is answered after the release has already run, and a surface that told
that approver they were about to release something would be describing an act
that already happened. The run is suspended AT the stage being answered, so
the stages the flow names after it are exactly what resolving it lets the
pipeline continue into.
"""

from __future__ import annotations

from typing import Any


def stage_position(run: dict[str, Any], stage: str) -> dict[str, Any]:
    """Return this stage's index, its flow's length, and what follows it.

    An empty ``remaining`` means nothing follows, so resolving the gate
    completes the run rather than releasing anything.
    """
    from yoke_core.domain.approval import parse_flow_stages

    names = [entry.name for entry in parse_flow_stages(run["stages"])]
    index = names.index(stage) if stage in names else -1
    return {
        "index": index,
        "total": len(names),
        "remaining": names[index + 1 :] if index >= 0 else [],
    }


__all__ = ["stage_position"]
