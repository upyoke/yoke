"""Append a lint's check identity and the canonical field-note footer.

Every Yoke PreToolUse lint emits a denial whose message text is operator-
facing. This helper is the single point through which all lint denial-emit
sites append the canonical ``field_note_text.FOOTER`` so the directive +
basic recipe + help pointer reach the operator at the exact moment a Yoke
guardrail blocks an action.

Design rules locked into this module:

* Pure rendering — no I/O or logging; recovery text remains unchanged.
* Idempotent — calling the helper on already-footered text short-circuits and
  retains one identity line and one footer. This protects callers that funnel
  through more than one denial-shaping helper from duplicating either block.
* ``rule_id`` is the check id shown to the person or agent whose tool call was
  refused. The audit emitter receives that same id separately.
"""

from __future__ import annotations

from yoke_contracts.hook_runner.denial_identity import attach_check_id
from yoke_contracts.field_note_text import FOOTER


def append_field_note_footer(denial_text: str, rule_id: str) -> str:
    """Return ``denial_text`` with its check id and ``FOOTER`` appended.

    Idempotency: if ``denial_text`` already ends with ``FOOTER`` (with or
    without a trailing newline), the input is returned unchanged. Empty
    ``denial_text`` returns a blank line + FOOTER so the footer alone never
    masquerades as the full denial.

    ``rule_id`` must be non-empty so a newly registered guard cannot emit an
    anonymous denial. It appears immediately before the shared footer.
    """
    stripped = denial_text.rstrip("\n")
    if stripped.endswith(FOOTER):
        footered = denial_text
    else:
        footered = f"{denial_text}\n\n{FOOTER}"
    return attach_check_id(footered, rule_id)


__all__ = ("append_field_note_footer",)
