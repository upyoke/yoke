"""Body-free payloads and diagnostic projections for relay reports."""

from __future__ import annotations

from collections.abc import Mapping

from yoke_contracts.session_control.evidence import redacted_evidence_document
from yoke_harness.session_relay_runtime import RelayAdapterResult


def launch_payload(
    relay_id: str,
    job: Mapping[str, object],
    result: RelayAdapterResult,
) -> dict[str, object]:
    return {
        "relay_id": relay_id,
        "job_kind": "launch",
        "job_id": str(job.get("job_id") or ""),
        "lease_id": str(job.get("lease_id") or ""),
        "result": result.result_code,
        "native_id": result.native_session_id,
        "adapter_revision": result.adapter_revision,
        "evidence": result.evidence,
    }


def diagnostic_outcome_fields(
    relay_id: str,
    machine_id: str,
    result: RelayAdapterResult,
) -> dict[str, object]:
    evidence = redacted_evidence_document(result.evidence)
    reference = evidence.get("native_diagnostic_ref")
    failure_class = evidence.get("native_error_class")
    availability = evidence.get("diagnostic_availability")
    if not any((reference, failure_class, availability)):
        return {}
    return {
        "relay_id": relay_id,
        "machine_id": machine_id,
        "native_diagnostic_ref": reference if isinstance(reference, str) else None,
        "native_diagnostic_command": evidence.get("native_diagnostic_command"),
        "diagnostic_expires_at": evidence.get("diagnostic_expires_at"),
        "diagnostic_availability": availability,
        "native_error_class": failure_class,
        "native_error_step": evidence.get("native_error_step"),
    }


__all__ = ["diagnostic_outcome_fields", "launch_payload"]
