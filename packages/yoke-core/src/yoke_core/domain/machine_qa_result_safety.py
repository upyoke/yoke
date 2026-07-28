"""Compatibility imports for client-safe Machine QA result guards."""

from yoke_harness.machine_qa_result_safety import (
    ensure_secret_free_result,
    redact_machine_qa_value,
)


__all__ = ["ensure_secret_free_result", "redact_machine_qa_value"]
