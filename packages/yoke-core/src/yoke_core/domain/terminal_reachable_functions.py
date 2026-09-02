"""The mutating functions a person reaches before any harness session exists.

Onboarding is the first thing a stranger runs and the last place a
missing declaration should surface. The dispatcher refuses a mutating
call that cannot name a harness session, which is right for agent work
and wrong for a plain terminal: the onboarding wizard's Apply, the
project install it drives, and the CLI recipes a new user is taught all
run in a shell no harness ever touched. Those functions declare
``ambient_session_required=False`` and bind the operating actor instead
(:mod:`yoke_core.domain.session_less_actor_binding`).

That declaration lives on each registry entry, one per function, and a
per-function declaration is exactly the kind that gets forgotten: a live
install stopped at its final Apply stage because
``project_structure.patch.apply`` never carried one, and the message it
produced told the operator to file a field-note. Nothing in the registry
could have caught that, because nothing in the registry knows which
functions a person without a session actually reaches.

This module is that missing fact. Each id below is reachable from a
surface a person drives with no harness session, and
:func:`undeclared_terminal_reachable` names any that stopped declaring
it. The paired contract test fails on the registry, not on the
stranger's machine.

Read-only functions never need declaring: the dispatcher's session
requirement applies only to mutating calls, so this set holds the
mutating ones alone.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional, Tuple

#: What ``yoke onboard``'s Apply stages and the project install they drive
#: write. Every one of these runs in the wizard's own process, which is a
#: terminal process: the machine has no registered session until the first
#: harness starts, and on a brand-new machine that has not happened yet.
ONBOARDING_APPLY: frozenset[str] = frozenset({
    "harness.machine_report.upsert",
    "onboard.checklist.init",
    "project.git.bootstrap",
    "project.install.run",
    "project.refresh.run",
    "project.snapshot.sync",
    "project.uninstall.run",
    "project_structure.patch.apply",
    "projects.capability_settings.merge",
    "projects.capability_settings.remove",
    "projects.capability_settings.set",
    "projects.create",
    "projects.environment_settings.merge",
    "projects.github_binding.bind",
    "projects.github_binding.unbind",
    "projects.update",
})

#: The ``yoke`` recipes a new user is taught to run directly in a shell —
#: the Local Terminal Helpers table in the Yoke command router, the
#: field-note directive every skill and denial repeats, and the identity
#: and org setup a self-hosted or hosted operator performs before their
#: first session exists.
TERMINAL_RECIPES: frozenset[str] = frozenset({
    "board.rebuild.run",
    "deployment_flows.create",
    "hook.evaluate.run",
    "identity.invite.create",
    "identity.invite.revoke",
    "identity.link.set",
    "items.create",
    "organizations.domain.set",
    "organizations.settings.merge",
    "ouroboros.field_note.append",
    "projects.capability_secret.set",
    "sessions.begin",
})

TERMINAL_REACHABLE_FUNCTION_IDS: frozenset[str] = (
    ONBOARDING_APPLY | TERMINAL_RECIPES
)

_SURFACES: Tuple[Tuple[str, frozenset[str]], ...] = (
    ("onboarding Apply", ONBOARDING_APPLY),
    ("plain-terminal CLI recipe", TERMINAL_RECIPES),
)


def surface_for(function_id: str) -> str:
    """Name the surface a person reaches ``function_id`` from, or ``""``."""
    names = [name for name, ids in _SURFACES if function_id in ids]
    return " and ".join(names)


def undeclared_terminal_reachable(
    lookup: Any, ids: Optional[Iterable[str]] = None,
) -> Tuple[Tuple[str, str], ...]:
    """Return ``(function_id, why)`` for every id that fails the contract.

    ``lookup`` is the registry lookup. An id that is not registered at
    all fails too: a contract naming a function nobody registers is a
    contract nobody enforces.
    """
    findings: list[Tuple[str, str]] = []
    for function_id in sorted(
        TERMINAL_REACHABLE_FUNCTION_IDS if ids is None else ids
    ):
        entry = lookup(function_id)
        if entry is None:
            findings.append((
                function_id,
                f"reachable from {surface_for(function_id)} but not registered",
            ))
            continue
        if entry.ambient_session_required:
            findings.append((
                function_id,
                f"reachable from {surface_for(function_id)} with no harness "
                "session, so its registry entry must declare "
                "ambient_session_required=False",
            ))
    return tuple(findings)


__all__ = [
    "ONBOARDING_APPLY",
    "TERMINAL_REACHABLE_FUNCTION_IDS",
    "TERMINAL_RECIPES",
    "surface_for",
    "undeclared_terminal_reachable",
]
