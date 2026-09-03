"""Canonical type vocabulary for the Yoke dependency model.

This module is the canonical home for the dependency model's value
types: gate-point and satisfaction enums plus the ``GateResult`` and
``DependencyEdge`` namedtuples.

``yoke_core.domain.dependencies`` and the package-level
``yoke_core.domain`` re-export these names so callers can import the
public dependency vocabulary from either stable surface.

Key concepts:

- **Gate point** describes *when* the dependency matters in the
  dependent item's lifecycle: ``activation`` (don't start),
  ``integration`` (work in parallel but land later), or ``closure``
  (don't close until blocker reaches a milestone).
- **Satisfaction condition** describes *what* must be true about the
  blocking item for the dependency to be considered resolved:
  ``status:done``, ``status:implemented``, ``fact:merged``, or
  ``fact:deployed:<environment-name>``.
"""

from __future__ import annotations

from enum import Enum
from typing import NamedTuple, Optional


FACT_DEPLOYED_PREFIX = "fact:deployed:"


# ---------------------------------------------------------------------------
# Enums -- canonical vocabulary for the dependency model
# ---------------------------------------------------------------------------


class GatePoint(str, Enum):
    """When in the dependent's lifecycle a dependency is enforced.

    DB column: ``item_dependencies.gate_point``

    - ``ACTIVATION``: Do not start the dependent yet.
    - ``INTEGRATION``: May work in parallel, but the dependent must
      land (merge) after the blocker.
    - ``CLOSURE``: The dependent may not be considered complete until the
      blocker reaches a stronger milestone.
    - ``COORDINATION_ONLY``: no path-claim mutex; parallel activation
      allowed; merge-time conflict resolution only. The edge is the
      operator's explicit assertion that two items touch overlapping
      files but no lifecycle ordering is required — the path-claim
      classifier treats the pair as compatible and lets both register
      and activate concurrently. Any same-hunk conflict surfaces as a
      normal git merge conflict at PR-merge time, handled by
      ``yoke_core.engines.merge_worktree``. Lifecycle gate evaluation
      (``evaluate_batch_gates`` etc.) continues to ignore this gate
      point — that side of the contract is unchanged.
    """

    ACTIVATION = "activation"
    INTEGRATION = "integration"
    CLOSURE = "closure"
    COORDINATION_ONLY = "coordination_only"

    @classmethod
    def from_db(cls, value: str) -> "GatePoint":
        """Resolve a DB string to its enum member."""
        for member in cls:
            if member.value == value:
                return member
        raise ValueError(f"Unknown gate_point: {value!r}")


class Satisfaction(str, Enum):
    """What must be true about the blocker for the dependency to clear.

    DB column: ``item_dependencies.satisfaction``

    - ``STATUS_DONE``: Blocking item must reach ``done``.
    - ``STATUS_IMPLEMENTED``: Blocking item must reach ``implemented``,
      ``release``, or ``done``.
    - ``FACT_MERGED``: Blocking item's merge must be confirmed by canonical
      fact (for example ``merged_at``) or branch ancestry.
    - ``fact:deployed:<environment-name>``: A succeeded deployment run for
      the blocker's project and named environment must carry the blocker.
    """

    STATUS_DONE = "status:done"
    STATUS_IMPLEMENTED = "status:implemented"
    FACT_MERGED = "fact:merged"

    @classmethod
    def _missing_(cls, value: object) -> "Satisfaction" | None:
        environment = deployed_environment(str(value))
        if environment is None:
            return None
        member = str.__new__(cls, str(value))
        member._name_ = f"FACT_DEPLOYED_{environment}"
        member._value_ = str(value)
        return member

    @classmethod
    def from_db(cls, value: str) -> "Satisfaction":
        """Resolve a DB string to its enum member."""
        try:
            return cls(value)
        except ValueError as exc:
            raise ValueError(
                f"Unknown satisfaction: {value!r}; accepted grammar: "
                f"{SATISFACTION_GRAMMAR}"
            ) from exc


SATISFACTION_GRAMMAR = (
    "status:done | status:implemented | fact:merged | "
    "fact:deployed:<environment-name>"
)


def deployed_environment(satisfaction: str) -> str | None:
    """Return the named environment from a deployed-fact value."""
    if not satisfaction.startswith(FACT_DEPLOYED_PREFIX):
        return None
    environment = satisfaction[len(FACT_DEPLOYED_PREFIX):]
    if not environment or environment != environment.strip():
        return None
    return environment


def satisfaction_is_known(satisfaction: str) -> bool:
    """Whether *satisfaction* matches the complete accepted grammar."""
    try:
        Satisfaction.from_db(satisfaction)
    except ValueError:
        return False
    return True


# ---------------------------------------------------------------------------
# Evaluation result
# ---------------------------------------------------------------------------


class GateResult(NamedTuple):
    """Outcome of evaluating a single dependency gate."""

    satisfied: bool
    reason: str


# ---------------------------------------------------------------------------
# Dependency edge record
# ---------------------------------------------------------------------------


class DependencyEdge(NamedTuple):
    """A single dependency relationship with evaluation context."""

    dep_id: int
    dependent_item: str
    blocking_item: str
    gate_point: str
    satisfaction: str
    rationale: str
    blocking_status: Optional[str]
    blocking_worktree: Optional[str]


# ---------------------------------------------------------------------------
# Predicate helpers -- shared call sites instead of duplicated string checks
# ---------------------------------------------------------------------------


def is_coordination_only(gate_point: str) -> bool:
    """True when gate_point names the directionless mutex affordance."""
    return gate_point == GatePoint.COORDINATION_ONLY.value


def is_activation_gate(gate_point: str) -> bool:
    """True when gate_point names a lifecycle activation gate."""
    return gate_point == GatePoint.ACTIVATION.value
