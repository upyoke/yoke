"""Where each harness states the effort a turn actually ran at.

``harness_sessions.reasoning_effort`` records only what a session's own
artifact says it used. Configuration files are starting defaults that a
session can override, and a catalog default names what a model offers,
not what this turn ran, so neither is ever read for it.

Effort is a per-turn fact: an operator can change it mid-session, so the
newest statement is the served one. Whether a reader can afford to keep
looking after the model is known depends on how it reads, which is the
second declaration here.
"""

from __future__ import annotations

from typing import Mapping

from yoke_contracts.harness_family_identity import (
    CLAUDE_FAMILY,
    CODEX_FAMILY,
    CURSOR_FAMILY,
)

#: The artifact field that states each turn's served effort, per family.
SERVED_EFFORT_SOURCES: Mapping[str, str] = {
    CLAUDE_FAMILY: "transcript assistant row top-level effort",
    CODEX_FAMILY: "rollout turn_context.payload.effort",
    CURSOR_FAMILY: "served variant name suffix in the conversation store",
}

#: Families whose served facts are re-read on every hook, not only until
#: the model lands. Codex folds its rollout incrementally from a stored
#: offset, so each hook reads only the bytes the rollout gained, and its
#: hook payload names the model, which would otherwise settle a session
#: before any turn stated its effort. Claude re-reads a bounded transcript
#: tail on every user prompt, which is when its effort can change; Cursor's
#: effort is part of the served model name, so a change is a model change.
SERVED_FACTS_FOLLOWED_EVERY_HOOK = frozenset({CODEX_FAMILY})


def follows_served_facts_every_hook(harness_id: str) -> bool:
    """True when this family's served facts are re-read on every hook."""
    return harness_id in SERVED_FACTS_FOLLOWED_EVERY_HOOK


__all__ = [
    "SERVED_EFFORT_SOURCES",
    "SERVED_FACTS_FOLLOWED_EVERY_HOOK",
    "follows_served_facts_every_hook",
]
