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
#: Separates the code a reason opens with from the diagnosis behind it.
REASON_DETAIL_SEPARATOR = ": "


def abort_reason_code(reason: Any) -> str:
    """Return the stable code a recorded abort reason opens with."""
    return str(reason or "").split(REASON_DETAIL_SEPARATOR, 1)[0]


__all__ = [
    "ABORT_REASON_MAX_LENGTH",
    "CASE_EXECUTION_ERROR_REASON",
    "CONTINUATION_PRE_HOST_ERROR_REASON",
    "REASON_DETAIL_SEPARATOR",
    "UNUSABLE_BEGIN_REASON",
    "abort_reason_code",
]
