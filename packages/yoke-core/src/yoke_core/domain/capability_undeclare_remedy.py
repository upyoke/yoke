"""The one sentence a fail-closed capability refusal owes its reader.

A declared capability's obligations are enforced as declared: when the
rung a capability promised is unreachable, the gate blocks rather than
quietly running the weaker path. That leaves the operator holding a
refusal with two real remedies — repair what the declaration promised, or
deliberately undeclare the capability so the project stops promising it.
Only the first is obvious from the refusal text, so every fail-closed
capability refusal appends this sentence, and it is written once here so
the recipe cannot drift between the places that raise.
"""

from __future__ import annotations

#: The registered command that removes a capability row, and therefore the
#: obligations derived from it.
UNDECLARE_COMMAND = "yoke projects capability-settings remove"


def undeclare_remedy(
    capability_type: str,
    *,
    project: str = "",
    consequence: str = "",
) -> str:
    """Name deliberate undeclaration as the second remedy for one refusal.

    ``consequence`` says what the project falls back to once the capability
    is gone, because an operator weighing the two remedies needs to know
    what they are choosing, not just how to type it.
    """
    target = project or "<project>"
    remedy = (
        f"Either repair what the {capability_type!r} capability declares, or "
        "deliberately undeclare it: "
        f"`{UNDECLARE_COMMAND} --project {target} "
        f"--cap-type {capability_type} --base <settings-as-read>`"
    )
    if consequence:
        remedy = f"{remedy} ({consequence})"
    return remedy + "."


__all__ = ["UNDECLARE_COMMAND", "undeclare_remedy"]
