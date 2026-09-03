"""The record one bridge diagnosis builds as it goes.

A capability whose precondition failed is reported as not run, naming the
check that stopped it, rather than as a second failure -- one missing privacy
grant produced five red lines before, and every one of them read like an
independent problem.
"""

from __future__ import annotations

from typing import Any

from yoke_contracts.machine_qa_terminal_bridge import (
    TERMINAL_APP_CONTROL_UNAVAILABLE_ERROR_CODE,
    TERMINAL_BRIDGE_CHECKS,
    TERMINAL_BRIDGE_RECOVERY,
)


class BridgeDiagnosisReport:
    """One ordered run of every bridge capability against one host."""

    def __init__(self, *, expected_console_user: str | None) -> None:
        self.expected_console_user = expected_console_user
        self.rows: list[dict[str, Any]] = []
        self.host: dict[str, Any] = {}
        self.blocked_by: str | None = None

    def record(
        self,
        name: str,
        *,
        ok: bool,
        observed: dict[str, Any],
        error_code: str | None = None,
    ) -> bool:
        """Record one capability's verdict and return whether it passed."""
        row: dict[str, Any] = {"name": name, "ok": ok, "observed": observed}
        if not ok:
            code = error_code or TERMINAL_APP_CONTROL_UNAVAILABLE_ERROR_CODE
            row["error_reason"] = code
            row["recovery"] = TERMINAL_BRIDGE_RECOVERY[code]
            self.blocked_by = self.blocked_by or name
        self.rows.append(row)
        return ok

    def close_unreached(self) -> None:
        """Mark every capability the run never got to, naming what stopped it."""
        recorded = {row["name"] for row in self.rows}
        for name in TERMINAL_BRIDGE_CHECKS:
            if name in recorded:
                continue
            self.rows.append(
                {
                    "name": name,
                    "ok": False,
                    "outcome": "not_run",
                    "blocked_by": self.blocked_by,
                    "observed": {},
                }
            )

    def first_failure_code(self) -> str | None:
        """Return the error code of the earliest capability that failed."""
        for row in self.rows:
            if not row["ok"]:
                return str(row.get("error_reason") or "") or None
        return None

    def evidence(self) -> dict[str, Any]:
        """Return the secret-free document this diagnosis submits."""
        return {
            "host": self.host,
            "checks": self.rows,
            "first_failed_check": self.blocked_by,
        }


__all__ = ["BridgeDiagnosisReport"]
