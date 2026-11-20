"""Native case setup and durable machine settings recovery within the QA lease."""

from yoke_contracts.machine_qa_failures import HostControlLocalError
from yoke_contracts.test_machine_types import HostActionResult
from yoke_core.domain.machine_qa_fixture_validation import (
    validate_post_state_assertions,
    validate_setup_operations,
)
from yoke_core.domain.machine_qa_recipe_contracts import WINDOWS_SETTINGS_JOURNAL


class NativeWindowsFixture:
    def __init__(self, control):
        self.control = control
        self.closed = False
        self.journal_captured = False

    @staticmethod
    def _failure(operation_id, code, reason):
        row = {"id": operation_id, "outcome": "failed", "reason": str(reason)}
        if isinstance(reason, HostControlLocalError):
            row.update(reason=reason.detail, diagnostics=list(reason.diagnostics))
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
        for operation_id, _ in normalized:
            if operation_id != WINDOWS_SETTINGS_JOURNAL:
                return self._unsupported(operation_id)
        if not normalized:
            return HostActionResult(True, {"operations": []})
        if len(normalized) != 1 or self.journal_captured or self.closed:
            return self._failure(
                WINDOWS_SETTINGS_JOURNAL, "windows_journal_declaration_invalid",
                "windows_journal_declaration_invalid: declare one journal operation before the case runs",
            )
        try:
            self.control.journal_settings("restore")
            self.control.journal_settings("capture")
        except RuntimeError as exc:
            return self._failure(WINDOWS_SETTINGS_JOURNAL, "windows_journal_capture_failed", exc)
        self.journal_captured = True
        return HostActionResult(True, {"operations": [{"id": WINDOWS_SETTINGS_JOURNAL, "outcome": "passed"}]})

    def execute_post_state_assertions(self, operations):
        normalized = validate_post_state_assertions(operations)
        if normalized:
            return self._unsupported(normalized[0][0])
        return HostActionResult(True, {"operations": []})

    def close(self):
        if self.closed or not self.journal_captured:
            self.closed = True
            return HostActionResult(True, {"operations": []})
        operation = "machine.settings-restore"
        try:
            self.control.journal_settings("restore")
        except RuntimeError as exc:
            return self._failure(operation, "windows_journal_restore_failed", exc)
        self.closed = True
        return HostActionResult(True, {"operations": [{"id": operation, "outcome": "passed"}]})
