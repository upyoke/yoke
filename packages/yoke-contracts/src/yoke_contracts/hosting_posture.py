"""What a project has decided about who runs its hosting.

Yoke can create and manage cloud infrastructure on AWS. It cannot do that
anywhere else — not on a PaaS, not on a VPS someone else provisioned, not on
an on-prem box. A project whose code lives on any of those is not misconfigured
and is not deferring a decision; it has a hosting arrangement Yoke does not
touch, and it needs a way to say so.

The three values below are that vocabulary, and they are deliberately three
rather than two: "I host this myself" and "I have not decided yet" lead to
different behavior everywhere downstream. A declared posture lets onboarding
propose a profile with no AWS capability in it and mark hosting settled; an
undeclared one means the question is still open and should be asked once.

Both the CLI that collects the answer and the engine that validates the stored
row read these names, so they live in the shared contracts package rather than
beside the AWS credential helpers — the posture is the wider fact, and the AWS
capability is one of its outcomes.
"""

from __future__ import annotations

from yoke_contracts.machine_config.capability_secrets import AWS_ADMIN_CAPABILITY

#: Yoke manages hosting for this project on AWS. The ``aws-admin`` capability
#: holds the deploy identity, so the posture and the capability type are the
#: same token: a project at this posture is exactly a project with that
#: capability, and spelling it twice would let the two drift apart.
POSTURE_YOKE_MANAGED_AWS = AWS_ADMIN_CAPABILITY

#: The operator runs the hosting. Yoke applies no infrastructure, asks for no
#: hosting credential, and proposes no infra Packs for this project.
POSTURE_NO_YOKE_MANAGED_HOST = "no-yoke-managed-host"

#: Not answered yet. This is the state of every project that has never reached
#: the question, and of every operator who chose to decide later. It is never
#: stored: absence of the row *is* this value.
POSTURE_UNDECIDED = "undecided"

#: Every legal posture, in the order the wizard offers them.
HOSTING_POSTURES = (
    POSTURE_YOKE_MANAGED_AWS,
    POSTURE_NO_YOKE_MANAGED_HOST,
    POSTURE_UNDECIDED,
)

#: The postures that are written down. ``undecided`` is expressed by the
#: absence of a row, the same way an absent ``deploy_defaults`` entry expresses
#: "no project default" — writing a row that says "nothing was decided" would
#: make absence and undecidedness two spellings of one state.
DECLARED_HOSTING_POSTURES = (
    POSTURE_YOKE_MANAGED_AWS,
    POSTURE_NO_YOKE_MANAGED_HOST,
)

#: Project Structure family holding the declaration. Singleton per project.
HOSTING_POSTURE_FAMILY = "hosting_posture"

#: Write-plan action id for the hosting step. The step records a decision; only
#: one of its outcomes also writes a credential, so the action is named for the
#: decision.
HOSTING_POSTURE_ACTION = "hosting-posture"


def is_declared(posture: str | None) -> bool:
    """Whether ``posture`` is an answer worth storing."""
    return posture in DECLARED_HOSTING_POSTURES


__all__ = [
    "DECLARED_HOSTING_POSTURES",
    "HOSTING_POSTURES",
    "HOSTING_POSTURE_ACTION",
    "HOSTING_POSTURE_FAMILY",
    "POSTURE_NO_YOKE_MANAGED_HOST",
    "POSTURE_UNDECIDED",
    "POSTURE_YOKE_MANAGED_AWS",
    "is_declared",
]
