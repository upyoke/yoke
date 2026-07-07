"""Append the canonical field-note footer to a lint's denial message.

Every Yoke PreToolUse lint emits a denial whose message text is operator-
facing. This helper is the single point through which all lint denial-emit
sites append the canonical ``field_note_text.FOOTER`` so the directive +
basic recipe + help pointer reach the operator at the exact moment a Yoke
guardrail blocks an action.

Design rules locked into this module:

* Pure passthrough — no I/O, no logging, no string mutation beyond the
  newline-glued FOOTER suffix.
* Idempotent — calling the helper on already-footered text short-circuits and
  returns the input unchanged. This protects callers that funnel through more
  than one denial-shaping helper from accidentally double-appending.
* ``rule_id`` is accepted but unused today. The parameter is a forward-looking
  hook for per-rule customization (e.g. routing rule-specific recipe hints
  into the FOOTER) without re-wiring every caller. The test suite locks the
  current passthrough behavior so a future change is visible as a diff.
"""

from __future__ import annotations

from yoke_contracts.field_note_text import FOOTER


def append_field_note_footer(denial_text: str, rule_id: str) -> str:
    """Return ``denial_text`` with the canonical field-note ``FOOTER`` appended.

    Idempotency: if ``denial_text`` already ends with ``FOOTER`` (with or
    without a trailing newline), the input is returned unchanged. Empty
    ``denial_text`` returns a blank line + FOOTER so the footer alone never
    masquerades as the full denial.

    ``rule_id`` is accepted for future per-rule customization (per-lint recipe
    pointer overrides). Today it is unused; callers pass their lint slug so
    the per-rule hook lands wherever it slots in without re-wiring every
    site.
    """
    # rule_id is intentionally unused — see docstring + module header.
    del rule_id

    stripped = denial_text.rstrip("\n")
    if stripped.endswith(FOOTER):
        return denial_text
    return f"{denial_text}\n\n{FOOTER}"


__all__ = ("append_field_note_footer",)
