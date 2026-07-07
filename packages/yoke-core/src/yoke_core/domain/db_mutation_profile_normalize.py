"""Field-shape normalizers for ``items.db_mutation_profile``.

Owns the per-field structural validators consumed by
:func:`yoke_core.domain.db_mutation_profile.validate`.  The error class
:class:`DbMutationProfileError` lives here as the canonical owner; the
front door re-exports it so historical importers keep working.

Cross-layer validation (capability lookup, module file existence, flow
binding) lives at the joint gate, not in this module.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Tuple


_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

MIGRATION_STRATEGY_ADDITIVE_ONLY = "additive_only"
MIGRATION_STRATEGY_HARD_CUTOVER = "hard_cutover"
MIGRATION_STRATEGY_EXPAND_CONTRACT = "expand_contract"
VALID_MIGRATION_STRATEGIES = frozenset({
    MIGRATION_STRATEGY_ADDITIVE_ONLY,
    MIGRATION_STRATEGY_HARD_CUTOVER,
    MIGRATION_STRATEGY_EXPAND_CONTRACT,
})

_MUTATION_INTENT_RETIRE = "retire"

# Reviewed-negative attestation keys — stamped by the ``db_claim.amend``
# workflow (never caller-supplied) when an amendment lands
# ``state="none"``. Their presence distinguishes an operator-reviewed
# no-DB decision from the implicit schema default; the prose-vs-claim
# gate reads them straight off the stored profile JSON.
REVIEWED_NEGATIVE_FIELD = "reviewed_negative"
REVIEWED_VALIDATED_AT_FIELD = "validated_at"

_STATE_NONE = "none"


class DbMutationProfileError(ValueError):
    """Raised when a ``db_mutation_profile`` payload fails schema validation."""


def stamp_reviewed_negative(
    profile: Dict[str, Any], *, validated_at: str
) -> Dict[str, Any]:
    """Return *profile* with the reviewed-negative attestation stamped.

    Only meaningful for ``state="none"`` profiles; declared profiles are
    returned unchanged. Workflow-internal — callers of ``db_claim.amend``
    never supply these keys themselves.
    """
    if profile.get("state") != _STATE_NONE:
        return profile
    stamped = dict(profile)
    stamped[REVIEWED_NEGATIVE_FIELD] = True
    stamped[REVIEWED_VALIDATED_AT_FIELD] = validated_at
    return stamped


def is_reviewed_negative(profile: Any) -> bool:
    """True when the parsed profile records an explicit reviewed-none decision.

    Accepts the parsed dict shape; JSON-string tolerance belongs to the
    callers' parse layer. Missing/false ``reviewed_negative`` or a
    non-``none`` state both yield False — the implicit schema default is
    never treated as reviewed.
    """
    if not isinstance(profile, dict):
        return False
    if profile.get("state") != _STATE_NONE:
        return False
    return profile.get(REVIEWED_NEGATIVE_FIELD) is True


def _check_slug(value: Any, *, field: str) -> str:
    if not isinstance(value, str):
        raise DbMutationProfileError(
            f"{field} must be a string; got {type(value).__name__}"
        )
    if not _SLUG_RE.match(value):
        raise DbMutationProfileError(
            f"{field} '{value}' must be slug-shape (lowercase alnum, '_', '-')"
        )
    return value


def _check_enum(value: Any, *, field: str, vocabulary: Iterable[str]) -> str:
    vocab = frozenset(vocabulary)
    if value not in vocab:
        raise DbMutationProfileError(
            f"{field} must be one of {sorted(vocab)}; got {value!r}"
        )
    return value


def _normalize_migration_modules(value: Any) -> List[str]:
    if not isinstance(value, list) or not value:
        raise DbMutationProfileError(
            "migration_modules must be a non-empty list of slug-shape identifiers"
        )
    normalized: List[str] = []
    for idx, entry in enumerate(value):
        _check_slug(entry, field=f"migration_modules[{idx}]")
        if entry in normalized:
            raise DbMutationProfileError(
                f"migration_modules contains duplicate entry '{entry}'"
            )
        if "/" in entry or entry.endswith(".py"):
            raise DbMutationProfileError(
                f"migration_modules[{idx}] '{entry}' must be a bare slug (no path, no extension)"
            )
        normalized.append(entry)
    return normalized


def _normalize_kind_list(value: Any, *, field: str, vocabulary: Iterable[str]) -> List[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise DbMutationProfileError(f"{field} must be a list")
    vocab = frozenset(vocabulary)
    normalized: List[str] = []
    for idx, entry in enumerate(value):
        if entry not in vocab:
            raise DbMutationProfileError(
                f"{field}[{idx}] '{entry}' not in {sorted(vocab)}"
            )
        if entry not in normalized:
            normalized.append(entry)
    return normalized


def _normalize_affected_surfaces(value: Any) -> List[Dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise DbMutationProfileError("affected_surfaces must be a list")
    normalized: List[Dict[str, Any]] = []
    for idx, entry in enumerate(value):
        if not isinstance(entry, dict):
            raise DbMutationProfileError(
                f"affected_surfaces[{idx}] must be an object with 'table'"
            )
        extra = set(entry.keys()) - {"table", "columns"}
        if extra:
            raise DbMutationProfileError(
                f"affected_surfaces[{idx}] has unknown keys: {sorted(extra)}"
            )
        table = entry.get("table")
        if not isinstance(table, str) or not table:
            raise DbMutationProfileError(
                f"affected_surfaces[{idx}].table must be a non-empty string"
            )
        columns = entry.get("columns")
        out: Dict[str, Any] = {"table": table}
        if columns is not None:
            if not isinstance(columns, list) or not all(isinstance(c, str) and c for c in columns):
                raise DbMutationProfileError(
                    f"affected_surfaces[{idx}].columns must be a list of non-empty strings"
                )
            out["columns"] = sorted(set(columns))
        normalized.append(out)
    return normalized


def _normalize_migration_strategy(
    payload: Dict[str, Any], *, mutation_intent: str
) -> Tuple[Optional[str], Optional[str]]:
    """Validate ``migration_strategy`` + ``migration_strategy_justification``.

    Apply mutations REQUIRE ``migration_strategy``; retire mutations MUST
    NOT carry one (the strategy axis is meaningless when nothing is being
    applied).  ``migration_strategy_justification`` is always optional —
    gate matrices in :mod:`yoke_core.domain.db_mutation_gate_strategy`
    enforce when a non-empty justification is required for a given
    ``breakage_policy x migration_strategy`` cell.
    """
    strategy = payload.get("migration_strategy")
    justification = payload.get("migration_strategy_justification")

    if mutation_intent == _MUTATION_INTENT_RETIRE:
        if strategy is not None:
            raise DbMutationProfileError(
                "migration_strategy is forbidden for mutation_intent='retire'; "
                "retire flows do not apply changes"
            )
        if justification is not None:
            raise DbMutationProfileError(
                "migration_strategy_justification is forbidden for "
                "mutation_intent='retire'"
            )
        return None, None

    if strategy is None:
        raise DbMutationProfileError(
            "migration_strategy is required for mutation_intent='apply'; "
            f"choose one of {sorted(VALID_MIGRATION_STRATEGIES)}"
        )
    _check_enum(
        strategy,
        field="migration_strategy",
        vocabulary=VALID_MIGRATION_STRATEGIES,
    )
    if justification is not None:
        if not isinstance(justification, str):
            raise DbMutationProfileError(
                "migration_strategy_justification must be a string"
            )
        if not justification.strip():
            raise DbMutationProfileError(
                "migration_strategy_justification, if present, must be non-empty"
            )
        justification = justification.strip()
    return strategy, justification


__all__ = [
    "DbMutationProfileError",
    "MIGRATION_STRATEGY_ADDITIVE_ONLY",
    "MIGRATION_STRATEGY_EXPAND_CONTRACT",
    "MIGRATION_STRATEGY_HARD_CUTOVER",
    "REVIEWED_NEGATIVE_FIELD",
    "REVIEWED_VALIDATED_AT_FIELD",
    "VALID_MIGRATION_STRATEGIES",
    "_check_enum",
    "_check_slug",
    "_normalize_affected_surfaces",
    "_normalize_kind_list",
    "_normalize_migration_modules",
    "_normalize_migration_strategy",
    "is_reviewed_negative",
    "stamp_reviewed_negative",
]
