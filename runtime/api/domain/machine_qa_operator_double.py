"""The operator-run half of the host-control double.

Reset already had a double; capture and diagnosis are modelled here so the
handler tests can exercise every receipt and refusal without a real Mac.
"""

from __future__ import annotations

from yoke_contracts.machine_qa_terminal_bridge import (
    TERMINAL_BRIDGE_CHECKS,
    TERMINAL_SSH_UNAVAILABLE_ERROR_CODE,
)
from yoke_core.domain.host_control_runner import HostActionResult


#: What a modelled capture reports having written. The number only has to be
#: positive and stable; the receipt's shape is what these tests assert.
CAPTURED_ENTRY_COUNT = 3


class FakeOperatorOperations:
    """Model capture and diagnosis outcomes a test asks the host to report."""

    home: str
    refuse_capture: str | None
    bridge_failure: str | None
    captured_destinations: list[str]

    def diagnose_terminal_bridge(self) -> HostActionResult:
        """Report every registered bridge capability, in order."""
        rows = [
            {"name": name, "ok": name != self.bridge_failure, "observed": {}}
            for name in TERMINAL_BRIDGE_CHECKS
        ]
        if self.bridge_failure is None:
            return HostActionResult(True, {"host": {}, "checks": rows})
        failed = next(index for index, row in enumerate(rows) if not row["ok"])
        rows[failed]["error_reason"] = TERMINAL_SSH_UNAVAILABLE_ERROR_CODE
        rows[failed]["recovery"] = "repair the host"
        for row in rows[failed + 1 :]:
            row.update({"ok": False, "outcome": "not_run"})
        return HostActionResult(
            False,
            {"host": {}, "checks": rows, "first_failed_check": self.bridge_failure},
            TERMINAL_SSH_UNAVAILABLE_ERROR_CODE,
        )

    def capture_golden_baseline(
        self,
        destination: str,
        *,
        probes_document: str | None = None,
    ) -> HostActionResult:
        """Model a capture that writes one new baseline, or refuses by name."""
        self.captured_destinations.append(destination)
        if self.refuse_capture is not None:
            return HostActionResult(
                False,
                {
                    "destination": destination,
                    "refusal": {
                        "reason": "yoke_residue",
                        "path": f"{self.home}/.yoke",
                        "recovery": "reset the host first",
                    },
                },
                self.refuse_capture,
            )
        return HostActionResult(
            True,
            {
                "destination": destination,
                "captured_entries": CAPTURED_ENTRY_COUNT,
                "captured_kilobytes": 2048,
                "manifest_digest": "a" * 64,
                "probes_digest": "b" * 64,
            },
        )


__all__ = ["CAPTURED_ENTRY_COUNT", "FakeOperatorOperations"]
