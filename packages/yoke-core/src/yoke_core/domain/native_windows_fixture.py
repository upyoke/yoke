"""Native case setup and durable machine settings recovery within the QA lease."""

from yoke_contracts.test_machine_types import HostActionResult
from yoke_core.domain.machine_qa_fixture_validation import (
    validate_post_state_assertions,
    validate_setup_operations,
)


class NativeWindowsFixture:
    def __init__(self, control):
        self.control = control
        self.closed = False
        control.journal_settings("restore")
        control.journal_settings("capture")

    def _batch(self, operations, validator):
        normalized = validator(operations)
        rows = []
        for operation_id, parameters in normalized:
            # POSIX recipes must be replaced with native argv assertions; never
            # turn a Linux shell fragment into a successful Windows setup.
            rows.append(
                {
                    "id": operation_id,
                    "outcome": "failed",
                    "reason": "native_windows_fixture_required: author this setup as native PowerShell argv in the case; the POSIX fixture operation cannot run on Windows",
                }
            )
            return HostActionResult(
                False, {"operations": rows}, "native_windows_fixture_required"
            )
        return HostActionResult(True, {"operations": rows})

    def execute_setup_operations(self, operations):
        return self._batch(operations, validate_setup_operations)

    def execute_post_state_assertions(self, operations):
        return self._batch(operations, validate_post_state_assertions)

    def close(self):
        if self.closed:
            return HostActionResult(True, {"operations": []})
        try:
            self.control.journal_settings("restore")
        except RuntimeError as exc:
            return HostActionResult(
                False,
                {
                    "operations": [
                        {
                            "id": "machine.settings-restore",
                            "outcome": "failed",
                            "reason": str(exc),
                        }
                    ]
                },
                "windows_journal_restore_failed",
            )
        self.closed = True
        return HostActionResult(
            True,
            {
                "operations": [
                    {
                        "id": "machine.settings-restore",
                        "outcome": "passed",
                    }
                ]
            },
        )
