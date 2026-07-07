"""Validator and default for the ``items.db_compatibility_attestation`` field.

The attestation is the safety argument behind a ``pre_merge_safe`` claim on
the sibling ``db_mutation_profile``.  Declaration is not proof: the profile
declares what the mutation is, the attestation argues why pre-merge ``main``
stays true after it lands.

Schema shape::

    {
        "frozen_at": null | "2026-04-22T17:52:49Z",  # UTC ISO-8601 Z
        "pre_merge_readers_writers": [
            {"path": "...", "symbol": "...", "role": "reader" | "writer"}
        ],
        "invariants": ["<short structured claim>", ...],
        "rehearsal_commands": ["python3 -m pytest ...", ...],
        "residual_risk_notes": "<required non-empty for pre_merge_safe>",
        "rehearsal_outcomes": [  # append-only; Yoke writes
            {"command": "...", "verdict": "pass" | "fail", "observed_at": "..."}
        ],
        "class_escalations": [   # append-only; scanner / rehearsal / operator
            {"from": "pre_merge_safe", "to": "pre_merge_breaking", "reason": "...",
             "source": "scanner" | "rehearsal" | "operator", "observed_at": "..."}
        ]
    }

The empty default ``{}`` is the shape stored before any attestation is
authored.  ``validate`` accepts the empty object unchanged so tickets whose
profile is ``state="none"`` never need to author an attestation.

For attestations on a ``pre_merge_safe`` profile the joint gate at
``idea → refining-idea`` will demand the four authored fields; this
per-write validator enforces only structural correctness — the joint gate
owns cross-field semantics.
"""

from __future__ import annotations

import copy
import json
from typing import Any, Dict, List, Optional


# Authored fields (operator-supplied).  When the profile is
# ``pre_merge_safe`` these must all be present and non-empty;
# the joint gate enforces that.  Per-write validation only checks shape.
AUTHORED_FIELDS = frozenset({
    "pre_merge_readers_writers",
    "invariants",
    "rehearsal_commands",
    "residual_risk_notes",
})

# Yoke-maintained append-only companions.
APPEND_ONLY_FIELDS = frozenset({
    "rehearsal_outcomes",
    "class_escalations",
})

# Freeze timestamp stamped by the joint gate on pass.
FREEZE_FIELD = "frozen_at"

ALL_FIELDS = AUTHORED_FIELDS | APPEND_ONLY_FIELDS | {FREEZE_FIELD}

VALID_ROLES = frozenset({"reader", "writer"})


NEGATIVE_DEFAULT: Dict[str, Any] = {}


class DbCompatibilityAttestationError(ValueError):
    """Raised when a ``db_compatibility_attestation`` payload fails validation."""


def negative_default() -> Dict[str, Any]:
    """Return a fresh deep copy of :data:`NEGATIVE_DEFAULT`."""
    return copy.deepcopy(NEGATIVE_DEFAULT)


def _require_string(value: Any, *, field: str, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise DbCompatibilityAttestationError(
            f"{field} must be a string; got {type(value).__name__}"
        )
    if not allow_empty and value == "":
        raise DbCompatibilityAttestationError(f"{field} must not be empty")
    return value


def _normalize_readers_writers(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        raise DbCompatibilityAttestationError(
            "pre_merge_readers_writers must be a list"
        )
    normalized: List[Dict[str, Any]] = []
    for idx, entry in enumerate(value):
        if not isinstance(entry, dict):
            raise DbCompatibilityAttestationError(
                f"pre_merge_readers_writers[{idx}] must be an object"
            )
        extra = set(entry.keys()) - {"path", "symbol", "role"}
        if extra:
            raise DbCompatibilityAttestationError(
                f"pre_merge_readers_writers[{idx}] has unknown keys: {sorted(extra)}"
            )
        path = _require_string(entry.get("path", ""), field=f"pre_merge_readers_writers[{idx}].path")
        role = entry.get("role")
        if role not in VALID_ROLES:
            raise DbCompatibilityAttestationError(
                f"pre_merge_readers_writers[{idx}].role must be one of {sorted(VALID_ROLES)}; got {role!r}"
            )
        out: Dict[str, Any] = {"path": path, "role": role}
        symbol = entry.get("symbol")
        if symbol is not None:
            out["symbol"] = _require_string(symbol, field=f"pre_merge_readers_writers[{idx}].symbol", allow_empty=True)
        normalized.append(out)
    return normalized


def _normalize_string_list(value: Any, *, field: str) -> List[str]:
    if not isinstance(value, list):
        raise DbCompatibilityAttestationError(f"{field} must be a list")
    normalized: List[str] = []
    for idx, entry in enumerate(value):
        normalized.append(_require_string(entry, field=f"{field}[{idx}]"))
    return normalized


def _normalize_outcomes(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        raise DbCompatibilityAttestationError("rehearsal_outcomes must be a list")
    normalized: List[Dict[str, Any]] = []
    for idx, entry in enumerate(value):
        if not isinstance(entry, dict):
            raise DbCompatibilityAttestationError(
                f"rehearsal_outcomes[{idx}] must be an object"
            )
        # Structural only — envelope shape is Yoke-authored; reject
        # nothing unknown here, since future fields may be added by the
        # rehearsal runner without a schema bump.
        normalized.append(dict(entry))
    return normalized


def _normalize_escalations(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        raise DbCompatibilityAttestationError("class_escalations must be a list")
    normalized: List[Dict[str, Any]] = []
    for idx, entry in enumerate(value):
        if not isinstance(entry, dict):
            raise DbCompatibilityAttestationError(
                f"class_escalations[{idx}] must be an object"
            )
        normalized.append(dict(entry))
    return normalized


def _normalize_frozen_at(value: Any) -> Optional[str]:
    if value is None:
        return None
    frozen = _require_string(value, field=FREEZE_FIELD)
    # Structural-only check: joint gate owns the stamping; here we just
    # verify shape.  Full ISO-8601 validation lives at the freeze site.
    if not frozen.endswith("Z"):
        raise DbCompatibilityAttestationError(
            f"{FREEZE_FIELD} must be UTC ISO-8601 ending in 'Z'; got {frozen!r}"
        )
    return frozen


def validate(payload: Any) -> Dict[str, Any]:
    """Validate and normalize a ``db_compatibility_attestation`` payload.

    The empty object ``{}`` is always accepted as the pre-authoring shape.
    """
    if not isinstance(payload, dict):
        raise DbCompatibilityAttestationError(
            f"db_compatibility_attestation must be a JSON object; got {type(payload).__name__}"
        )

    if not payload:
        return {}

    unknown = set(payload.keys()) - ALL_FIELDS
    if unknown:
        raise DbCompatibilityAttestationError(
            f"db_compatibility_attestation has unknown keys: {sorted(unknown)}"
        )

    result: Dict[str, Any] = {}
    if FREEZE_FIELD in payload:
        result[FREEZE_FIELD] = _normalize_frozen_at(payload[FREEZE_FIELD])
    if "pre_merge_readers_writers" in payload:
        result["pre_merge_readers_writers"] = _normalize_readers_writers(
            payload["pre_merge_readers_writers"]
        )
    if "invariants" in payload:
        result["invariants"] = _normalize_string_list(
            payload["invariants"], field="invariants"
        )
    if "rehearsal_commands" in payload:
        result["rehearsal_commands"] = _normalize_string_list(
            payload["rehearsal_commands"], field="rehearsal_commands"
        )
    if "residual_risk_notes" in payload:
        result["residual_risk_notes"] = _require_string(
            payload["residual_risk_notes"],
            field="residual_risk_notes",
            allow_empty=True,  # joint gate checks non-emptiness on pre_merge_safe
        )
    if "rehearsal_outcomes" in payload:
        result["rehearsal_outcomes"] = _normalize_outcomes(payload["rehearsal_outcomes"])
    if "class_escalations" in payload:
        result["class_escalations"] = _normalize_escalations(payload["class_escalations"])

    return result


def canonical_json(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def validate_json_string(raw: str) -> str:
    """Parse *raw* as JSON, validate, and return compact canonical JSON."""
    if raw is None or raw == "":
        raise DbCompatibilityAttestationError(
            "db_compatibility_attestation payload is empty"
        )
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DbCompatibilityAttestationError(f"malformed JSON: {exc}") from exc
    return canonical_json(validate(payload))


NEGATIVE_DEFAULT_JSON = canonical_json(NEGATIVE_DEFAULT)


def _safe_parse_dict(raw: Optional[str]) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def check_authored_fields_frozen(
    current_raw: Optional[str],
    new_raw: Optional[str],
) -> Optional[str]:
    """Enforce authored-field immutability once ``frozen_at`` is stamped.

    Given the currently stored attestation JSON and the candidate new JSON,
    return an error message if the write would mutate an authored field or
    clear ``frozen_at`` while the stamp is still in place.  Return ``None``
    when the write is allowed.

    Frozen-state semantics:
        * ``current.frozen_at`` absent → no freeze in force; any write is
          allowed (validator still enforces structural correctness).
        * ``current.frozen_at`` present →
            * Candidate must preserve the same ``frozen_at`` value.
              Clearing the stamp through the write-path is forbidden;
              re-entering ``refining-idea`` owns unfreeze.
            * Every authored field (``pre_merge_readers_writers``,
              ``invariants``, ``rehearsal_commands``,
              ``residual_risk_notes``) must match the stored value
              byte-for-byte.  Append-only companions (outcomes,
              escalations) remain writable.
    """
    current = _safe_parse_dict(current_raw)
    if current is None:
        return None
    frozen_at = current.get(FREEZE_FIELD)
    if not frozen_at:
        return None

    candidate = _safe_parse_dict(new_raw)
    if candidate is None:
        return None

    new_frozen = candidate.get(FREEZE_FIELD)
    if new_frozen != frozen_at:
        return (
            "db_compatibility_attestation.frozen_at is stamped "
            f"({frozen_at}); write-path cannot clear or change it. "
            "Re-enter refining-idea to unfreeze authored fields."
        )

    for field in sorted(AUTHORED_FIELDS):
        if current.get(field) != candidate.get(field):
            return (
                f"db_compatibility_attestation.{field} is frozen "
                f"(frozen_at={frozen_at}); re-enter refining-idea to unfreeze."
            )
    return None


__all__ = [
    "ALL_FIELDS",
    "APPEND_ONLY_FIELDS",
    "AUTHORED_FIELDS",
    "DbCompatibilityAttestationError",
    "FREEZE_FIELD",
    "NEGATIVE_DEFAULT",
    "NEGATIVE_DEFAULT_JSON",
    "VALID_ROLES",
    "canonical_json",
    "check_authored_fields_frozen",
    "negative_default",
    "validate",
    "validate_json_string",
]
