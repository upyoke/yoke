"""What close-out requires, for the two surfaces that have to agree on it.

``yoke merge item`` refuses a terminal transition on some workflows unless the
caller supplies ``--result`` and ``--verification``. The steering report has to
print a close-out command that will *not* be refused. That is one question
asked from opposite sides — the command that refuses and the report that
recommends — so the answer lives here once and both read it.

They did not, and it showed. The report composed its recipe from the item
reference alone, so every evidence-gated row it printed named the un-gated
form; nine rows carried that line at once, and each seat that followed one
paid a denial before finding the command that runs.
"""

from __future__ import annotations

#: Workflows whose terminal transition requires an execution-evidence record.
EVIDENCE_GATED_WORKFLOWS = frozenset({"dash"})

#: Stand-ins a reader replaces with the landing's own facts. The recommended
#: command names the flags rather than omitting them, so the values are
#: composed from what the reader knows instead of discovered through a refusal.
RESULT_PLACEHOLDER = "<what landed>"
VERIFICATION_PLACEHOLDER = "<how it was verified>"


def terminal_transition_is_evidence_gated(workflow_id: str) -> bool:
    """Whether close-out on *workflow_id* refuses without the evidence flags."""
    return str(workflow_id or "") in EVIDENCE_GATED_WORKFLOWS


def close_out_command(public_ref: str, *, workflow_id: str) -> str:
    """The ``yoke merge item`` invocation that runs for this item's workflow.

    An unknown or absent workflow gets the bare form: naming flags a workflow
    does not gate on would send a reader to compose values nothing asks for,
    and the command's own refusal remains the authority either way.
    """
    command = f"yoke merge item {public_ref}"
    if not terminal_transition_is_evidence_gated(workflow_id):
        return command
    return (
        f'{command} --result "{RESULT_PLACEHOLDER}" '
        f'--verification "{VERIFICATION_PLACEHOLDER}"'
    )


__all__ = [
    "EVIDENCE_GATED_WORKFLOWS",
    "RESULT_PLACEHOLDER",
    "VERIFICATION_PLACEHOLDER",
    "close_out_command",
    "terminal_transition_is_evidence_gated",
]
