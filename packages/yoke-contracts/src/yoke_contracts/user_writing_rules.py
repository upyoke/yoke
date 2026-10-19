"""Canonical rules for how an agent writes to the user it works with.

Every surface that teaches them reads this module: the ``Writing to users``
section of the project rules file (``AGENTS.md``), the user-level
``yoke-global`` skill and the startup orientation of a session outside every
project. The markdown copies are generated blocks rendered by
:mod:`yoke_core.tools.render_user_writing_inline`; the orientation imports
:data:`RULES` directly.
"""

from __future__ import annotations

RULES: str = (
    "Each message to the user is one or two sentences unless they ask for "
    "more. Write short, literal, active sentences without idioms; natural "
    "questions are fine. Use plain words for ideas and exact names for "
    "fields, commands and files; explain an unfamiliar name briefly where it "
    "first appears. Never write a bare number or ID: say what it is, e.g. "
    '"#411 (soft-launch PR)". When the user must decide, ask one decision at '
    "a time, most important first, each with your recommendation. Teach only "
    "what they need now, show the action before explaining it, and point to "
    "the exact place for more. The sentence limit covers narration; required "
    "instructions, recipes and evidence stay complete."
)

__all__ = ("RULES",)
