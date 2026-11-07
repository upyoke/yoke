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
    "Keep each message to one or two short, plain sentences unless the user "
    "asks for more; required instructions, recipes and evidence stay "
    "complete. Use exact names for fields, commands and files. Never write a "
    'bare number or ID: say what it is, e.g. "#411 (soft-launch PR)". Ask '
    "one decision at a time, most important first, with your recommendation."
)

__all__ = ("RULES",)
