"""Where each harness discovers the user-level ``yoke-global`` skill.

Full Yoke skills are per-project copies (``.agents/skills/yoke`` in each
checkout). The one user-level skill is ``yoke-global``: it serves a session
opened outside every project and leads it to a project folder. Its name
differs from the project ``yoke`` skill, so it never shadows one.

The skill lives once, in the shared user skill folder
``~/.agents/skills/yoke-global``. Codex and Cursor read that folder natively;
Claude Code reads only ``~/.claude/skills``, so Claude gets a symlink to the
shared folder — the same shape as a project's ``.claude/skills/yoke`` link.
This module is the single source for those facts. The renderer copies each
entry into ``runtime/harness/<harness_id>/manifest.json`` under
``global_skill`` (documented in ``runtime/harness/manifest-global-skill.md``)
and :mod:`yoke_contracts.global_skill_install` installs from it.

``verified_on_surface`` names a surface only where a live session listed the
installed skill; ``evidence`` says what was observed. Cursor also reads
``~/.claude/skills`` and ``~/.codex/skills`` when its third-party skill import
is on; the Claude link resolves to the same folder.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

GLOBAL_SKILL_NAME = "yoke-global"

#: The shared user skill folder, relative to the home directory.
SHARED_SKILLS_DIR = ".agents/skills"

#: ``shared`` reads the shared folder natively; ``link`` needs a symlink.
Placement = Literal["shared", "link"]


@dataclass(frozen=True)
class HarnessGlobalSkill:
    """One harness family's user-level skill discovery fact."""

    harness_home: str
    user_skills_dir: str
    placement: Placement
    verified_on_surface: str
    evidence: str

    def to_json(self) -> dict[str, object]:
        return {
            "name": GLOBAL_SKILL_NAME,
            "harness_home": self.harness_home,
            "user_skills_dir": self.user_skills_dir,
            "placement": self.placement,
            "shared_skill_dir": f"~/{SHARED_SKILLS_DIR}/{GLOBAL_SKILL_NAME}",
            "verified_on_surface": self.verified_on_surface,
            "evidence": self.evidence,
        }


HARNESS_GLOBAL_SKILLS: dict[str, HarnessGlobalSkill] = {
    "claude-code": HarnessGlobalSkill(
        harness_home="~/.claude",
        user_skills_dir="~/.claude/skills",
        placement="link",
        verified_on_surface="",
        evidence=(
            "Claude Code reads user skills from ~/.claude/skills and follows a "
            "symlinked skill folder, as every project's .claude/skills/yoke "
            "link shows. No live session has listed the user-level link yet."
        ),
    ),
    "codex": HarnessGlobalSkill(
        harness_home="$CODEX_HOME or ~/.codex",
        user_skills_dir=f"~/{SHARED_SKILLS_DIR}",
        placement="shared",
        verified_on_surface="codex-cli",
        evidence=(
            "Observed 2026-10-17: codex-cli 0.161.0 started outside every "
            "project listed yoke-global installed in $HOME/.agents/skills."
        ),
    ),
    "cursor": HarnessGlobalSkill(
        harness_home="~/.cursor",
        user_skills_dir=f"~/{SHARED_SKILLS_DIR}",
        placement="shared",
        verified_on_surface="",
        evidence=(
            "cursor-agent 2026.10.16 resolves user skill folders ~/.cursor/skills "
            "and ~/.agents/skills (read from its shipped bundle). No live "
            "session has listed the installed skill yet."
        ),
    ),
}


def global_skill_for_harness(harness_id: str) -> HarnessGlobalSkill:
    """Return one harness family's fact; an unknown id is a contract error."""
    try:
        return HARNESS_GLOBAL_SKILLS[harness_id]
    except KeyError:
        raise KeyError(
            f"no user-level skill discovery recorded for harness {harness_id!r}; "
            "add it to yoke_contracts.harness_global_skill.HARNESS_GLOBAL_SKILLS"
        ) from None


def harness_home(harness_id: str, home: Path) -> Path:
    """The folder whose presence means the harness is installed."""
    if harness_id == "codex":
        return Path(os.environ.get("CODEX_HOME") or (home / ".codex"))
    return home / global_skill_for_harness(harness_id).harness_home.removeprefix("~/")


def shared_skill_dir(home: Path) -> Path:
    return home / SHARED_SKILLS_DIR / GLOBAL_SKILL_NAME


def link_path(harness_id: str, home: Path) -> Path:
    """Where a ``link`` harness discovers the skill."""
    fact = global_skill_for_harness(harness_id)
    return home / fact.user_skills_dir.removeprefix("~/") / GLOBAL_SKILL_NAME


__all__ = (
    "GLOBAL_SKILL_NAME",
    "HARNESS_GLOBAL_SKILLS",
    "HarnessGlobalSkill",
    "SHARED_SKILLS_DIR",
    "global_skill_for_harness",
    "harness_home",
    "link_path",
    "shared_skill_dir",
)
