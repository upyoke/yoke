"""What a project has decided about having a runnable test suite.

The gate that blocks an item's review runs the project's registered
verification command. A project with no suite to register reaches that gate
with nothing to run, and a gate with nothing to run reports green — so the
absence of a suite has to be something a project can say out loud, or every
reader downstream has to guess between "no tests" and "nobody asked yet".

Exactly one value is written down. A project that *has* a command already says
so through its ``registered-command-*`` QA plan; spelling that fact a second
time here would let the two drift apart, and the drift would be invisible
precisely when it mattered. So the stored value only ever means "the operator
looked at this repository and attested there is no suite to bind", and the
absence of a row means the question is open.

The attestation carries a required reason. That requirement is what separates
an attestation from an omission: an idea-only repository, a content site, and a
client who will not pay for tests yet are three different situations, and the
reviewer who later reads the gate deserves to know which one they are in.

Both the surface that collects the answer and the engine that validates the
stored row read these names, so they live in the shared contracts package
rather than beside either one.
"""

from __future__ import annotations

#: The operator attested that this project has no runnable suite to register.
#: Review of an item is gated on an explicit implementation review instead of
#: on a verification command, and registering a command is refused until the
#: attestation is cleared.
POSTURE_ATTESTED_NO_TESTS = "attested-no-tests"

#: Not answered yet. This is the state of every project that has never reached
#: the question. It is never stored: absence of the row *is* this value.
POSTURE_UNDECIDED = "undecided"

#: The postures that are written down. ``undecided`` is expressed by the
#: absence of a row, the same way an absent ``deploy_defaults`` entry expresses
#: "no project default" — writing a row that says "nothing was decided" would
#: make absence and undecidedness two spellings of one state.
DECLARED_VERIFICATION_POSTURES = (POSTURE_ATTESTED_NO_TESTS,)

#: Project Structure family holding the declaration. Singleton per project.
VERIFICATION_POSTURE_FAMILY = "verification_posture"


def is_declared(posture: str | None) -> bool:
    """Whether ``posture`` is an answer worth storing."""
    return posture in DECLARED_VERIFICATION_POSTURES


__all__ = [
    "DECLARED_VERIFICATION_POSTURES",
    "POSTURE_ATTESTED_NO_TESTS",
    "POSTURE_UNDECIDED",
    "VERIFICATION_POSTURE_FAMILY",
    "is_declared",
]
