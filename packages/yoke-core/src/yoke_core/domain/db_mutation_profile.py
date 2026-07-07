"""Validator and default for the ``items.db_mutation_profile`` structured field.

Declares what governed DB mutation a ticket is performing against a
declared project ``migration_model``.  Every write path that persists
``db_mutation_profile`` MUST route through :func:`validate`.  Ad hoc JSON
construction in skill bodies is forbidden.

Schema shape (two-state)::

    # Negative default — no governed mutation declared:
    {"state": "none"}

    # Fully declared:
    {
        "state": "declared",
        "model_name": "primary",
        "mutation_intent": "apply" | "retire",
        "migration_modules": ["add_items_due_date", ...],
        "compatibility_class": "pre_merge_safe" | "pre_merge_breaking",
        "migration_strategy": "additive_only" | "hard_cutover" | "expand_contract",  # apply only
        "migration_strategy_justification": "string",                                # apply, optional
        "schema_kinds": ["additive" | "destructive" | "rebuild", ...],
        "data_kinds":   ["fill" | "transform" | "drop", ...],
        "affected_surfaces": [{"table": "items", "columns": ["due_date"]}],
        "count_preserving": true
    }

``compatibility_class`` is a SAFETY classification (does the diff
preserve readers/writers across the merge boundary?).
``migration_strategy`` is the AUTHOR'S DECLARATION about the operational
shape (additive-only, hard cutover, or expand-contract).  The two are
orthogonal: `pre_merge_safe + hard_cutover` is a clean drop-and-replace
that happens to keep readers happy; `pre_merge_breaking + hard_cutover`
is the founder-cutover slice that intentionally breaks compat in one
step.  Gate matrices read both axes — see
``yoke_core.domain.db_mutation_gate_strategy``.

Full cross-layer validation (capability lookup, migration-module
existence, cross-ticket overlap, flow reference) lives at the
``idea → refining-idea`` joint gate.  This module is the per-write
structural validator only — it verifies vocabulary, required fields, and
type shapes, then returns canonical JSON.
"""

from __future__ import annotations

import copy
import json
from typing import Any, Dict

from yoke_core.domain.db_mutation_profile_normalize import (
    MIGRATION_STRATEGY_ADDITIVE_ONLY,
    MIGRATION_STRATEGY_EXPAND_CONTRACT,
    MIGRATION_STRATEGY_HARD_CUTOVER,
    REVIEWED_NEGATIVE_FIELD,
    REVIEWED_VALIDATED_AT_FIELD,
    VALID_MIGRATION_STRATEGIES,
    DbMutationProfileError,
    _check_enum,
    _check_slug,
    _normalize_affected_surfaces,
    _normalize_kind_list,
    _normalize_migration_modules,
    _normalize_migration_strategy,
    is_reviewed_negative,
    stamp_reviewed_negative,
)


STATE_NONE = "none"
STATE_DECLARED = "declared"
VALID_STATES = frozenset({STATE_NONE, STATE_DECLARED})

MUTATION_INTENT_APPLY = "apply"
MUTATION_INTENT_RETIRE = "retire"
VALID_MUTATION_INTENTS = frozenset({MUTATION_INTENT_APPLY, MUTATION_INTENT_RETIRE})

COMPATIBILITY_PRE_MERGE_SAFE = "pre_merge_safe"
COMPATIBILITY_PRE_MERGE_BREAKING = "pre_merge_breaking"
VALID_COMPATIBILITY_CLASSES = frozenset({
    COMPATIBILITY_PRE_MERGE_SAFE,
    COMPATIBILITY_PRE_MERGE_BREAKING,
})

VALID_SCHEMA_KINDS = frozenset({"additive", "destructive", "rebuild"})
VALID_DATA_KINDS = frozenset({"fill", "transform", "drop"})

# Tables that are appended to during the apply itself (every Yoke tool
# call emits events; the agent running the migration writes to these
# tables as a side effect of running it). The verify gate's pre/post
# total-row-count parity check cannot succeed on these tables even when
# the migration UPDATE is row-count-preserving, so we refuse the
# count_preserving=true declaration up front and route operators to the
# module-level invariants() hook for semantic correctness.
LIVE_APPEND_TABLES = frozenset({"events"})

# Canonical key order for the declared-state payload.  Serialization is
# sort_keys=True for stability, but the ordering here matches the spec's
# read order and is documented for future contributors.
_DECLARED_KEYS = (
    "state",
    "model_name",
    "mutation_intent",
    "migration_modules",
    "compatibility_class",
    "migration_strategy",
    "migration_strategy_justification",
    "schema_kinds",
    "data_kinds",
    "affected_surfaces",
    "count_preserving",
)
_REQUIRED_DECLARED_KEYS = frozenset({
    "state", "model_name", "mutation_intent", "migration_modules",
    "compatibility_class",
})
_OPTIONAL_DECLARED_KEYS = frozenset({
    "schema_kinds", "data_kinds", "affected_surfaces", "count_preserving",
    "migration_strategy", "migration_strategy_justification",
})
_THEOREM_BEARING_KEYS = frozenset(_DECLARED_KEYS) - {"state"}


NEGATIVE_DEFAULT: Dict[str, Any] = {"state": STATE_NONE}


def negative_default() -> Dict[str, Any]:
    """Return a fresh deep copy of :data:`NEGATIVE_DEFAULT`."""
    return copy.deepcopy(NEGATIVE_DEFAULT)


def validate(payload: Any) -> Dict[str, Any]:
    """Validate and normalize a ``db_mutation_profile`` payload.

    Returns a normalized dict; raises :class:`DbMutationProfileError` on any
    schema or vocabulary violation.  Cross-layer checks (capability lookup,
    module file existence, flow binding) happen at the joint gate, not here.
    """
    if not isinstance(payload, dict):
        raise DbMutationProfileError(
            f"db_mutation_profile must be a JSON object; got {type(payload).__name__}"
        )

    state = payload.get("state")
    if state not in VALID_STATES:
        raise DbMutationProfileError(
            f"state must be one of {sorted(VALID_STATES)}; got {state!r}"
        )

    if state == STATE_NONE:
        present = _THEOREM_BEARING_KEYS & set(payload.keys())
        if present:
            raise DbMutationProfileError(
                f"state='none' forbids theorem-bearing fields; found: {sorted(present)}"
            )
        return {"state": STATE_NONE}

    missing = _REQUIRED_DECLARED_KEYS - set(payload.keys())
    if missing:
        raise DbMutationProfileError(
            f"state='declared' missing required keys: {sorted(missing)}"
        )
    unknown = set(payload.keys()) - (_REQUIRED_DECLARED_KEYS | _OPTIONAL_DECLARED_KEYS)
    if unknown:
        raise DbMutationProfileError(
            f"db_mutation_profile has unknown keys: {sorted(unknown)}"
        )

    model_name = _check_slug(payload["model_name"], field="model_name")
    mutation_intent = _check_enum(
        payload["mutation_intent"],
        field="mutation_intent",
        vocabulary=VALID_MUTATION_INTENTS,
    )
    migration_modules = _normalize_migration_modules(payload["migration_modules"])
    compatibility_class = _check_enum(
        payload["compatibility_class"],
        field="compatibility_class",
        vocabulary=VALID_COMPATIBILITY_CLASSES,
    )

    schema_kinds = _normalize_kind_list(
        payload.get("schema_kinds"),
        field="schema_kinds",
        vocabulary=VALID_SCHEMA_KINDS,
    )
    data_kinds = _normalize_kind_list(
        payload.get("data_kinds"),
        field="data_kinds",
        vocabulary=VALID_DATA_KINDS,
    )
    affected_surfaces = _normalize_affected_surfaces(payload.get("affected_surfaces"))

    count_preserving = payload.get("count_preserving", True)
    if not isinstance(count_preserving, bool):
        raise DbMutationProfileError("count_preserving must be a strict boolean")

    if count_preserving:
        live_hits = sorted({
            s["table"] for s in affected_surfaces
            if s.get("table") in LIVE_APPEND_TABLES
        })
        if live_hits:
            raise DbMutationProfileError(
                f"count_preserving=true is not allowed when affected_surfaces "
                f"names a live append-active log table ({live_hits}); the "
                f"verify gate's pre/post total-row-count parity check cannot "
                f"succeed against these tables because the apply itself emits "
                f"events into the same table. Set count_preserving=false and "
                f"rely on the migration module's invariants() hook for "
                f"semantic correctness (e.g. asserting post-apply residue=0 "
                f"and all severities canonical). See "
                f"docs/db-reference/items-and-epics.md '## DB Claim — the "
                f"unified amendment workflow' for the canonical amend payload shape."
            )

    migration_strategy, migration_strategy_justification = _normalize_migration_strategy(
        payload, mutation_intent=mutation_intent,
    )

    out: Dict[str, Any] = {
        "state": STATE_DECLARED,
        "model_name": model_name,
        "mutation_intent": mutation_intent,
        "migration_modules": migration_modules,
        "compatibility_class": compatibility_class,
        "schema_kinds": schema_kinds,
        "data_kinds": data_kinds,
        "affected_surfaces": affected_surfaces,
        "count_preserving": count_preserving,
    }
    if migration_strategy is not None:
        out["migration_strategy"] = migration_strategy
    if migration_strategy_justification is not None:
        out["migration_strategy_justification"] = migration_strategy_justification
    return out


def canonical_json(payload: Dict[str, Any]) -> str:
    """Serialize a validated payload to compact, sort-key-stable JSON."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def validate_json_string(raw: str) -> str:
    """Parse *raw* as JSON, validate, and return compact canonical JSON.

    Raises :class:`DbMutationProfileError` on empty input, malformed JSON,
    or any schema violation surfaced by :func:`validate`.
    """
    if raw is None or raw == "":
        raise DbMutationProfileError("db_mutation_profile payload is empty")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DbMutationProfileError(f"malformed JSON: {exc}") from exc
    return canonical_json(validate(payload))


NEGATIVE_DEFAULT_JSON = canonical_json(NEGATIVE_DEFAULT)


def _safe_parse_dict(raw: Any) -> Dict[str, Any]:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return parsed


def check_model_name_frozen(
    current_attestation_raw: Any,
    current_profile_raw: Any,
    new_profile_raw: Any,
) -> Any:
    """Enforce profile ``model_name`` immutability once the sibling
    ``db_compatibility_attestation.frozen_at`` is stamped.

    Returns an error string if the write would change ``model_name`` while
    the attestation freeze is in force; returns ``None`` otherwise.

    The check only fires when both sides of the comparison declare a
    ``model_name`` (current ``state="declared"`` and new ``state="declared"``).
    Transitions from ``state="none"`` to ``state="declared"`` with a freshly
    declared ``model_name`` are allowed — those represent initial
    declaration, not a rename.  Transitions from ``state="declared"`` back
    to ``state="none"`` with the attestation still frozen are rejected.
    """
    attestation = _safe_parse_dict(current_attestation_raw)
    frozen_at = attestation.get("frozen_at")
    if not frozen_at:
        return None

    current = _safe_parse_dict(current_profile_raw)
    new = _safe_parse_dict(new_profile_raw)
    old_model = current.get("model_name")
    new_model = new.get("model_name")
    if not old_model:
        return None
    if old_model == new_model:
        return None

    return (
        "db_mutation_profile.model_name is frozen "
        f"(attestation.frozen_at={frozen_at}); re-enter refining-idea "
        "before rebinding to another model."
    )


__all__ = [
    "COMPATIBILITY_PRE_MERGE_BREAKING",
    "COMPATIBILITY_PRE_MERGE_SAFE",
    "DbMutationProfileError",
    "MIGRATION_STRATEGY_ADDITIVE_ONLY",
    "MIGRATION_STRATEGY_EXPAND_CONTRACT",
    "MIGRATION_STRATEGY_HARD_CUTOVER",
    "MUTATION_INTENT_APPLY",
    "MUTATION_INTENT_RETIRE",
    "NEGATIVE_DEFAULT",
    "NEGATIVE_DEFAULT_JSON",
    "REVIEWED_NEGATIVE_FIELD",
    "REVIEWED_VALIDATED_AT_FIELD",
    "STATE_DECLARED",
    "STATE_NONE",
    "VALID_COMPATIBILITY_CLASSES",
    "VALID_DATA_KINDS",
    "VALID_MIGRATION_STRATEGIES",
    "VALID_MUTATION_INTENTS",
    "VALID_SCHEMA_KINDS",
    "VALID_STATES",
    "canonical_json",
    "check_model_name_frozen",
    "is_reviewed_negative",
    "negative_default",
    "stamp_reviewed_negative",
    "validate",
    "validate_json_string",
]
