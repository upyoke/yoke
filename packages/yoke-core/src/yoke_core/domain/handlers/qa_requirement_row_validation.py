"""Field-level validation shared by every QA requirement creation path.

The same row rules hold whether a case attaches to an item, to a deployment
run, or arrives inside a batch: a case names either a registered method or a
legacy kind, never both; it names the phase it gates; and its blocking mode,
provenance, and success policy come from the closed vocabularies the
database also checks. Keeping them here means one answer to those questions
rather than one per attachment shape.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from yoke_contracts.api.function_call import HandlerOutcome
from yoke_core.domain.handlers.qa import _error


def validate_row(row: Dict[str, Any], jsonpath: str) -> Optional[HandlerOutcome]:
    """Validate one add/add-batch row and return an error outcome or None.

    Mutates *row* in place through the canonical field normalizers.
    """
    from yoke_core.domain.qa_constants import (
        VALID_BLOCKING_MODES,
        _normalize_qa_kind,
        _normalize_qa_phase,
    )
    from yoke_core.domain.qa_requirement_policy_validation import (
        validate_requirement_source,
        validate_success_policy,
    )

    method_id = row.get("method_id")
    qa_kind = row.get("qa_kind")
    if (
        isinstance(method_id, str)
        and method_id.strip()
        and isinstance(qa_kind, str)
        and qa_kind.strip()
    ):
        return _error(
            "payload_invalid",
            "qa_kind and method_id are mutually exclusive",
            jsonpath=jsonpath,
        )
    qa_phase = row.get("qa_phase")
    if isinstance(method_id, str) and method_id.strip():
        row["method_id"] = method_id.strip()
        row["qa_kind"] = "method_case"
    elif not isinstance(qa_kind, str) or not qa_kind:
        return _error(
            "payload_invalid",
            "qa_kind or method_id is required",
            jsonpath=f"{jsonpath}.qa_kind",
        )
    if not isinstance(qa_phase, str) or not qa_phase:
        return _error(
            "payload_invalid",
            "qa_phase is required",
            jsonpath=f"{jsonpath}.qa_phase",
        )
    if not row.get("method_id"):
        row["qa_kind"] = _normalize_qa_kind(str(qa_kind))
    row["qa_phase"] = _normalize_qa_phase(qa_phase)

    blocking_mode = str(row.get("blocking_mode") or "blocking")
    if blocking_mode not in VALID_BLOCKING_MODES:
        return _error(
            "payload_invalid",
            "blocking_mode must be one of "
            f"{', '.join(VALID_BLOCKING_MODES)} (got {blocking_mode!r})",
            jsonpath=f"{jsonpath}.blocking_mode",
        )

    source_errors = validate_requirement_source(
        str(row.get("requirement_source") or "explicit"),
    )
    if source_errors:
        return _error(
            "payload_invalid",
            "; ".join(source_errors),
            jsonpath=f"{jsonpath}.requirement_source",
        )
    policy_errors = validate_success_policy(
        row["qa_kind"],
        row.get("success_policy"),
    )
    if policy_errors:
        return _error(
            "payload_invalid",
            "; ".join(policy_errors),
            jsonpath=f"{jsonpath}.success_policy",
        )
    return None


__all__ = ["validate_row"]
