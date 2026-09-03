"""The one approval policy shape every human gate declares.

A gate that asks people to decide names the same three things wherever it is
declared -- a workflow transition, a deployment flow stage, an item posture, a
QA evidence review: which project or org ROLES may answer, which named PEOPLE
may answer, and whether ANY one of them settles it or ALL of them must.

``any`` is the default because it is what every gate meant before the mode
existed -- the first approval from anyone listed resolves the request -- so a
policy stored without a mode keeps exactly the meaning it was written with.
``all`` asks for one decision per checked box: a checked role is satisfied by
any one current holder of that role, a named person only by that person.

Nothing checked is not an empty gate, it is no gate: a policy with no roles and
no actors gates nothing, which is why every declaration surface refuses to
store one rather than recording an obligation nobody can discharge.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Iterable, Optional

#: Roles a gate may address. ``admin`` is scoped to the project's org; the
#: other two are scoped to the project itself.
APPROVAL_ROLES = frozenset({"owner", "operator", "admin"})

APPROVAL_MODE_ANY = "any"
APPROVAL_MODE_ALL = "all"
APPROVAL_MODES = (APPROVAL_MODE_ANY, APPROVAL_MODE_ALL)
DEFAULT_APPROVAL_MODE = APPROVAL_MODE_ANY

APPROVAL_POLICY_KEYS = frozenset({"roles", "actors", "mode"})

#: How each addressed role reads to a person deciding.
APPROVAL_ROLE_LABELS = {
    "owner": "project owner",
    "operator": "project operator",
    "admin": "org admin",
}


@dataclass(frozen=True)
class ApprovalPolicy:
    """Who may answer one gate, and how many of them must."""

    roles: tuple[str, ...] = ()
    actors: tuple[int, ...] = ()
    mode: str = DEFAULT_APPROVAL_MODE

    @property
    def gates(self) -> bool:
        """Return whether this policy asks anyone for anything."""
        return bool(self.roles or self.actors)

    @property
    def requires_every_approver(self) -> bool:
        return self.mode == APPROVAL_MODE_ALL

    @property
    def box_count(self) -> int:
        """Count the checked boxes ``all`` mode needs one decision for each."""
        return len(self.roles) + len(self.actors)

    def as_dict(self) -> dict[str, Any]:
        return {
            "roles": list(self.roles),
            "actors": list(self.actors),
            "mode": self.mode,
        }

    def describe(self) -> str:
        """Render the addressees the way a gate message names them."""
        who = [APPROVAL_ROLE_LABELS.get(role, role) for role in self.roles]
        who.extend(f"actor {actor_id}" for actor_id in self.actors)
        if not who:
            return "no one"
        joiner = " and " if self.requires_every_approver else " or "
        return joiner.join(who)


def parse_approval_mode(raw: Any, *, path: str) -> str:
    """Return a validated mode, defaulting to ``any`` when none is declared."""
    if raw is None:
        return DEFAULT_APPROVAL_MODE
    if not isinstance(raw, str) or raw not in APPROVAL_MODES:
        raise ValueError(
            f"{path}.mode must be one of: {', '.join(APPROVAL_MODES)}"
        )
    return raw


def parse_approval_policy(
    raw: Any,
    *,
    path: str,
    allowed_roles: Iterable[str] = APPROVAL_ROLES,
    require_addressee: bool = True,
) -> ApprovalPolicy:
    """Validate one declared approval policy and return its typed shape.

    Raises ``ValueError`` naming *path* and the exact field at fault, so every
    declaration surface can render the same diagnosis in its own vocabulary.
    """
    if not isinstance(raw, Mapping):
        raise ValueError(f"{path} must be an object with roles, actors and mode")
    extra = set(raw) - APPROVAL_POLICY_KEYS
    if extra:
        raise ValueError(f"{path} has unknown fields: {sorted(extra)}")
    roles_raw = raw.get("roles") or []
    actors_raw = raw.get("actors") or []
    if not isinstance(roles_raw, list) or not isinstance(actors_raw, list):
        raise ValueError(f"{path} roles and actors must be arrays")
    if any(not isinstance(role, str) for role in roles_raw):
        raise ValueError(f"{path}.roles must be unique role names")
    roles = [str(value) for value in roles_raw]
    if len(roles) != len(set(roles)):
        raise ValueError(f"{path}.roles must be unique role names")
    unknown = set(roles) - set(allowed_roles)
    if unknown:
        raise ValueError(f"{path}.roles has unknown values: {sorted(unknown)}")
    actors: list[int] = []
    for value in actors_raw:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{path}.actors must be unique positive integer actor ids")
        actors.append(int(value))
    if len(actors) != len(set(actors)):
        raise ValueError(f"{path}.actors must be unique positive integer actor ids")
    mode = parse_approval_mode(raw.get("mode"), path=path)
    if require_addressee and not roles and not actors:
        raise ValueError(f"{path} must name at least one role or actor")
    return ApprovalPolicy(
        roles=tuple(sorted(roles)),
        actors=tuple(sorted(set(actors))),
        mode=mode,
    )


def approval_policy_or_none(
    raw: Any,
    *,
    path: str,
) -> Optional[ApprovalPolicy]:
    """Return the declared policy, or ``None`` when nothing is declared."""
    if not raw:
        return None
    policy = parse_approval_policy(raw, path=path, require_addressee=False)
    return policy if policy.gates else None


__all__ = [
    "APPROVAL_MODE_ALL",
    "APPROVAL_MODE_ANY",
    "APPROVAL_MODES",
    "APPROVAL_POLICY_KEYS",
    "APPROVAL_ROLE_LABELS",
    "APPROVAL_ROLES",
    "ApprovalPolicy",
    "DEFAULT_APPROVAL_MODE",
    "approval_policy_or_none",
    "parse_approval_mode",
    "parse_approval_policy",
]
