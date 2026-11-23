"""Native case setup refuses POSIX fixture operations."""

from yoke_contracts.test_machine_types import HostActionResult
from yoke_core.domain.machine_qa_fixture_validation import (
    validate_post_state_assertions,
    validate_setup_operations,
)


class NativeWindowsFixture:
    def __init__(self, control):
        self.control = control
        self.closed = False

    @staticmethod
    def _failure(operation_id, code, reason):
        row = {"id": operation_id, "outcome": "failed", "reason": str(reason)}
        return HostActionResult(False, {"operations": [row]}, code)

    @classmethod
    def _unsupported(cls, operation_id):
        # POSIX recipes must be replaced with native argv assertions.
        return cls._failure(
            operation_id,
            "native_windows_fixture_required",
            "native_windows_fixture_required: author this operation as native PowerShell argv in the case",
        )

    def execute_setup_operations(self, operations):
        normalized = validate_setup_operations(operations)
        if normalized:
            return self._unsupported(normalized[0][0])
        return HostActionResult(True, {"operations": []})

    def execute_post_state_assertions(self, operations):
        normalized = validate_post_state_assertions(operations)
        if normalized:
            return self._unsupported(normalized[0][0])
        return HostActionResult(True, {"operations": []})

    def close(self):
        self.closed = True
        return HostActionResult(True, {"operations": []})
