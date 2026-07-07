"""Shared row model for Yoke operation inventory tables."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class _Row:
    shell_form: str
    family: str
    status: str
    reason: str
    proposed_function_id: Optional[str] = None


WRAPPED = "wrapped"
PERMANENT = "permanent"
PENDING = "pending"

REASON_WRAPPED_BY_YOKE_CLI = "wrapped_by_yoke_cli"
REASON_OPERATOR_BREAK_GLASS = "operator_break_glass"
REASON_TOOL_SHAPED = "tool_shaped"
REASON_NO_HANDLER_REGISTERED = "no_handler_registered"


def _w(shell_form: str, family: str) -> _Row:
    return _Row(shell_form, family, WRAPPED, REASON_WRAPPED_BY_YOKE_CLI)


def _p(shell_form: str, family: str, reason: str) -> _Row:
    return _Row(shell_form, family, PERMANENT, reason)


def _q(shell_form: str, family: str, fn_id: str) -> _Row:
    return _Row(
        shell_form, family, PENDING, REASON_NO_HANDLER_REGISTERED, fn_id,
    )


__all__ = [
    "_Row", "_w", "_p", "_q",
    "WRAPPED", "PERMANENT", "PENDING",
    "REASON_WRAPPED_BY_YOKE_CLI", "REASON_OPERATOR_BREAK_GLASS",
    "REASON_TOOL_SHAPED", "REASON_NO_HANDLER_REGISTERED",
]
