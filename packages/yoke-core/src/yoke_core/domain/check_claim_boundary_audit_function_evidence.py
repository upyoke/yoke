"""Function metadata and authorization evidence for claim-boundary audit."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from yoke_core.domain.yoke_function_dispatch_claim_evidence import (
    CLAIM_VERIFICATION_ALLOWED,
    CLAIM_VERIFICATION_PHASE,
)
from yoke_core.domain.yoke_function_registry import RegistryEntry, lookup


_AUDITED_FUNCTION_FAMILIES = (
    "items.structured_field",
    "items.section",
    "items.scalar",
    "items.progress_log",
    "lifecycle.transition",
    "workflow_item.epic_task",
    "workflow_item.epic_progress_note",
    "db_claim",
    "qa.requirement",
    "qa.run",
)
_ITEM_CLAIM_KINDS = frozenset({"item", "epic", "qa_subject"})


@dataclass(frozen=True)
class FunctionAuditMetadata:
    side_effects: tuple[str, ...]
    claim_required_kind: Optional[str]

    @property
    def is_claimed_mutation(self) -> bool:
        return bool(
            self.side_effects
            and self.claim_required_kind in _ITEM_CLAIM_KINDS
        )


@dataclass(frozen=True)
class ClaimVerificationSnapshot:
    decision: str
    required_kind: Optional[str]
    caller_session_id: Optional[str]
    holder_session_id: Optional[str]


@dataclass(frozen=True)
class SnapshotFinding:
    severity: str
    holder_session_id: Optional[str]
    caller_session_id: Optional[str]
    rationale: str


def _in_audited_family(function_name: str) -> bool:
    return any(
        function_name == family or function_name.startswith(family + ".")
        for family in _AUDITED_FUNCTION_FAMILIES
    )


def _ensure_registry_entry(function_name: str) -> Optional[RegistryEntry]:
    entry = lookup(function_name)
    if entry is not None:
        return entry
    from yoke_core.domain.handlers.__init_register__ import register_all_handlers

    register_all_handlers()
    return lookup(function_name)


def function_audit_metadata(
    context: dict,
    function_name: str,
) -> Optional[FunctionAuditMetadata]:
    """Resolve durable event metadata, falling back to today's registry."""
    if not function_name or not _in_audited_family(function_name):
        return None
    entry = _ensure_registry_entry(function_name)
    raw_effects = context.get("side_effects")
    if isinstance(raw_effects, (list, tuple)):
        effects = tuple(str(value) for value in raw_effects if value)
    else:
        effects = tuple(entry.side_effects) if entry is not None else ()
    if "claim_required_kind" in context:
        raw_kind = context.get("claim_required_kind")
        required_kind = str(raw_kind) if raw_kind is not None else None
    else:
        required_kind = entry.claim_required_kind if entry is not None else None
    return FunctionAuditMetadata(effects, required_kind)


def claimed_mutation_function_names() -> tuple[str, ...]:
    """Return exact in-scope function ids from authoritative registry rows."""
    from yoke_core.domain.handlers.__init_register__ import register_all_handlers
    from yoke_core.domain.yoke_function_registry import list_entries

    register_all_handlers()
    names = []
    for entry in list_entries():
        metadata = function_audit_metadata({}, entry.function_id)
        if metadata is not None and metadata.is_claimed_mutation:
            names.append(entry.function_id)
    return tuple(names)


def target_item_id(
    context: dict,
    metadata: FunctionAuditMetadata,
    fallback: object,
) -> Optional[int]:
    """Resolve claim subject from the typed target before the event index."""
    target = context.get("target")
    target = target if isinstance(target, dict) else {}
    verification = context.get("claim_verification")
    verification = verification if isinstance(verification, dict) else {}
    candidates = [target.get("item_id"), verification.get("target_item_id")]
    if metadata.claim_required_kind == "epic":
        candidates.extend(
            [target.get("epic_id"), verification.get("target_epic_id")]
        )
    candidates.append(fallback)
    for value in candidates:
        try:
            if value is not None:
                return int(str(value).replace("YOK-", ""))
        except (TypeError, ValueError):
            continue
    return None


def claim_verification_snapshot(
    context: dict,
) -> Optional[ClaimVerificationSnapshot]:
    """Return only evidence explicitly captured at the pre-handler boundary."""
    raw = context.get("claim_verification")
    if not isinstance(raw, dict) or raw.get("phase") != CLAIM_VERIFICATION_PHASE:
        return None
    required = raw.get("required_kind")
    return ClaimVerificationSnapshot(
        decision=str(raw.get("decision") or ""),
        required_kind=str(required) if required is not None else None,
        caller_session_id=(
            str(raw["caller_session_id"])
            if raw.get("caller_session_id")
            else None
        ),
        holder_session_id=(
            str(raw["holder_session_id"])
            if raw.get("holder_session_id")
            else None
        ),
    )


def classify_claim_verification(
    snapshot: ClaimVerificationSnapshot,
    metadata: FunctionAuditMetadata,
    event_caller: object,
) -> Optional[SnapshotFinding]:
    """Validate one durable pre-handler decision against event attribution."""
    caller = str(event_caller) if event_caller else None
    holder = snapshot.holder_session_id
    if snapshot.required_kind != metadata.claim_required_kind:
        return SnapshotFinding(
            "WARN", holder, caller,
            "pre-handler claim evidence disagrees with function metadata",
        )
    if snapshot.decision != CLAIM_VERIFICATION_ALLOWED:
        return SnapshotFinding(
            "WARN", holder, caller,
            "pre-handler evidence does not record an allowed claim decision",
        )
    if caller is None:
        return SnapshotFinding(
            "WARN", holder, None,
            "caller session not recorded on the event",
        )
    if snapshot.caller_session_id != caller:
        return SnapshotFinding(
            "FAIL", holder, caller,
            "event caller differs from the pre-handler verified caller",
        )
    if metadata.claim_required_kind in {"item", "epic"} and holder is None:
        return SnapshotFinding(
            "WARN", None, caller,
            "pre-handler evidence is missing the verified claim holder",
        )
    if holder is not None and holder != caller:
        return SnapshotFinding(
            "FAIL", holder, caller,
            "pre-handler claim holder differs from the event caller",
        )
    return None


__all__ = [
    "ClaimVerificationSnapshot",
    "FunctionAuditMetadata",
    "SnapshotFinding",
    "classify_claim_verification",
    "claim_verification_snapshot",
    "claimed_mutation_function_names",
    "function_audit_metadata",
    "target_item_id",
]
