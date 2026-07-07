"""Gate matrix that pairs ``projects.breakage_policy`` with
``db_mutation_profile.migration_strategy``.

Two axes, five cells.  ``additive_only`` is always allowed; the
remaining four cells split into two safe pairs and two
justification-required pairs::

    breakage_policy           x  migration_strategy   = result
    --------------------------------------------------------------------
    any                          additive_only          allow
    founder_cutover              hard_cutover           allow
    founder_cutover              expand_contract        block w/o justification
    compatibility_required       hard_cutover           block w/o justification
    compatibility_required       expand_contract        allow

Operator-facing error messages always name BOTH axes so the operator
knows which side to amend.  The matrix is used by:

* :mod:`...db_mutation_gate_idea` — joint gate at idea → refining-idea.
* :mod:`...migration_apply_live` and :mod:`...migration_apply_rehearse`
  — governed runner gates at apply / rehearsal time.

The matrix is intentionally pure — callers pass the resolved
``breakage_policy`` and the validated profile, and the helper returns a
list of operator-facing errors (empty on pass).  No DB reads happen
here; the breakage-policy lookup is owned by
:mod:`...projects_breakage_policy`.
"""

from __future__ import annotations

from typing import Any, List, Mapping

from yoke_core.domain.db_mutation_profile_normalize import (
    MIGRATION_STRATEGY_ADDITIVE_ONLY,
    MIGRATION_STRATEGY_EXPAND_CONTRACT,
    MIGRATION_STRATEGY_HARD_CUTOVER,
)
from yoke_core.domain.projects_breakage_policy import (
    POLICY_COMPATIBILITY_REQUIRED,
    POLICY_FOUNDER_CUTOVER,
)


def evaluate_strategy_matrix(
    *,
    breakage_policy: str,
    profile: Mapping[str, Any],
) -> List[str]:
    """Return operator-facing errors (empty on pass) for the strategy matrix.

    ``profile`` is a validated ``db_mutation_profile`` with
    ``state="declared"`` and ``mutation_intent="apply"``.  Callers should
    skip this helper for retire intent and for ``state="none"`` —
    matrix has nothing to check there.

    Raises ``ValueError`` if the caller misuses it (wrong state or wrong
    intent) — that's a programming error, not an operator-recoverable
    one.
    """
    state = profile.get("state")
    intent = profile.get("mutation_intent")
    if state != "declared":
        raise ValueError(
            f"strategy matrix only applies to state='declared'; got {state!r}"
        )
    if intent != "apply":
        raise ValueError(
            f"strategy matrix only applies to mutation_intent='apply'; "
            f"got {intent!r}"
        )

    strategy = profile.get("migration_strategy")
    justification = (profile.get("migration_strategy_justification") or "").strip()

    if strategy == MIGRATION_STRATEGY_ADDITIVE_ONLY:
        return []  # additive_only always allowed.

    if breakage_policy == POLICY_FOUNDER_CUTOVER:
        if strategy == MIGRATION_STRATEGY_HARD_CUTOVER:
            return []
        if strategy == MIGRATION_STRATEGY_EXPAND_CONTRACT:
            if justification:
                return []
            return [_block_message(
                breakage_policy=POLICY_FOUNDER_CUTOVER,
                migration_strategy=MIGRATION_STRATEGY_EXPAND_CONTRACT,
                why=(
                    "founder_cutover projects default to purge/hard cutover; "
                    "preserving old + new readers temporarily requires an "
                    "operator-authored justification"
                ),
            )]

    if breakage_policy == POLICY_COMPATIBILITY_REQUIRED:
        if strategy == MIGRATION_STRATEGY_EXPAND_CONTRACT:
            return []
        if strategy == MIGRATION_STRATEGY_HARD_CUTOVER:
            if justification:
                return []
            return [_block_message(
                breakage_policy=POLICY_COMPATIBILITY_REQUIRED,
                migration_strategy=MIGRATION_STRATEGY_HARD_CUTOVER,
                why=(
                    "compatibility_required projects need old + new "
                    "readers/writers to coexist; a hard cutover requires "
                    "an operator-authored justification (maintenance "
                    "window, approval, safety reason)"
                ),
            )]

    return [
        f"unrecognized strategy-matrix combination: "
        f"breakage_policy={breakage_policy!r}, "
        f"migration_strategy={strategy!r}"
    ]


def _block_message(
    *,
    breakage_policy: str,
    migration_strategy: str,
    why: str,
) -> str:
    return (
        f"strategy matrix blocks: breakage_policy={breakage_policy!r} + "
        f"migration_strategy={migration_strategy!r} requires non-empty "
        f"migration_strategy_justification — {why}. "
        f"Add a justification to the DB claim, or change the migration "
        f"strategy."
    )


__all__ = ["evaluate_strategy_matrix"]
