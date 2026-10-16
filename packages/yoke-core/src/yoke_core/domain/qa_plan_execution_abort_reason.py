"""The durable reason an ended QA plan execution carries, in two registers.

One column answers two audiences. Readers that route on *which class* of
failure ended an execution match a stable code; the person sent to inspect
that execution's release evidence needs to know *what* failed. So a reason
is the code, then the diagnosis behind it, and every classifying reader goes
through :func:`abort_reason_code` rather than comparing the whole string.

Keeping that split here, beside the codes themselves, is what stops a reason
that gained a diagnosis from silently reading as unrecognized.
"""

from __future__ import annotations

from typing import Any

ABORT_REASON_MAX_LENGTH = 200

#: A case raised while executing or recording, with a host contact possible.
CASE_EXECUTION_ERROR_REASON = "case-execution-or-recording-error"
#: A continuation raised before it could reach the host it inherited, so the
#: walk state that continuation exists to preserve is still intact.
CONTINUATION_PRE_HOST_ERROR_REASON = "continuation-pre-host-error"
#: A begun execution whose own begin response this client cannot run.
UNUSABLE_BEGIN_REASON = "plan-execution-begin-unusable"
#: Every independent chain ran and at least one case failed or errored.
CASE_FAILED_REASON = "qa-plan-case-failed"
#: The deployment run removed the execution's member while it was walking.
MEMBER_REMOVED_REASON = "deployment-member-removed"
#: Separates the code a reason opens with from the diagnosis behind it.
REASON_DETAIL_SEPARATOR = ": "


def abort_reason_code(reason: Any) -> str:
    """Return the stable code a recorded abort reason opens with."""
    return str(reason or "").split(REASON_DETAIL_SEPARATOR, 1)[0]


def member_removed(execution: Any) -> bool:
    """Whether an execution view was ended by its member's removal from the run.

    The abort a client sends after its case raised returns the execution as
    it stands. When the run had already removed the member, the execution is
    terminal with this reason and the abort changed nothing, so the case's
    error is the removal's consequence rather than a failure of its host.
    A view from a server that does not carry ``release_reason`` reads False.
    """
    return (
        isinstance(execution, dict)
        and execution.get("state") == "aborted"
        and abort_reason_code(execution.get("release_reason")) == MEMBER_REMOVED_REASON
    )


def case_failed_reason(requirement_ids: list[int]) -> str:
    """Name the failed cases, listing as many as the reason column holds."""
    prefix = f"{CASE_FAILED_REASON}{REASON_DETAIL_SEPARATOR}requirements "
    listed: list[str] = []
    for index, requirement_id in enumerate(requirement_ids):
        remaining = len(requirement_ids) - index - 1
        tail = f" and {remaining} more" if remaining else ""
        candidate = ", ".join([*listed, str(requirement_id)])
        if len(prefix + candidate + tail) > ABORT_REASON_MAX_LENGTH:
            return f"{prefix}{', '.join(listed)} and {remaining + 1} more"
        listed.append(str(requirement_id))
    return prefix + ", ".join(listed)


__all__ = [
    "ABORT_REASON_MAX_LENGTH",
    "CASE_EXECUTION_ERROR_REASON",
    "CASE_FAILED_REASON",
    "CONTINUATION_PRE_HOST_ERROR_REASON",
    "MEMBER_REMOVED_REASON",
    "REASON_DETAIL_SEPARATOR",
    "UNUSABLE_BEGIN_REASON",
    "abort_reason_code",
    "case_failed_reason",
    "member_removed",
]
