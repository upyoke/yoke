"""Where each harness discovers the user-level ``yoke-global`` skill.

Full Yoke skills are per-project copies (``.agents/skills/yoke`` in each
checkout). The one user-level skill is ``yoke-global``: it serves a session
opened outside every project and leads it to a project folder. Its name
differs from the project ``yoke`` skill, so it never shadows one.

The skill lives once, in the shared user skill folder
``~/.agents/skills/yoke-global``. Codex and Cursor read that folder natively;
Claude Code reads only ``~/.claude/skills``, so Claude gets its own copy of
the same skill file there. It is a real folder, not a link: native Windows
OpenSSH sessions run under Redirection Guard and do not follow a junction the
user created, so a linked skill was invisible to Claude started over SSH.
This module is the single source for those facts. The renderer copies each
entry into ``runtime/harness/<harness_id>/manifest.json`` under
``global_skill`` (documented in ``runtime/harness/manifest-global-skill.md``)
and :mod:`yoke_contracts.global_skill_install` installs from it.

``verified_on_surface`` names a surface only where a live session listed the
installed skill; ``evidence`` says what was observed. Cursor also reads
``~/.claude/skills`` and ``~/.codex/skills`` when its third-party skill import
is on; the Claude copy carries the same skill text.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

GLOBAL_SKILL_NAME = "yoke-global"

#: The shared user skill folder, relative to the home directory.
SHARED_SKILLS_DIR = ".agents/skills"

#: ``shared`` reads the shared folder natively; ``copy`` needs its own copy.
Placement = Literal["shared", "copy"]


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
        placement="copy",
        verified_on_surface="",
        evidence=(
            "Copy placement not yet observed live. Observed 2026-11-27 (QA "
            "artifact 59365): claude-cli 2.1.332 over native Windows SSH did "
            "not list yoke-global through the earlier ~/.claude/skills "
            "junction, which Redirection Guard refused to traverse."
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
        verified_on_surface="cursor-cli",
        evidence=(
            "Observed 2026-10-18: cursor-agent 2026.10.14 started outside every "
            "project listed yoke-global from $HOME/.agents/skills with the "
            "~/.claude/skills link moved aside, and through the link otherwise."
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


def shared_skill_dir(home: Path) -> Path:
    return home / SHARED_SKILLS_DIR / GLOBAL_SKILL_NAME


def copy_path(harness_id: str, home: Path) -> Path:
    """Where a ``copy`` harness discovers its copy of the skill."""
    fact = global_skill_for_harness(harness_id)
    return home / fact.user_skills_dir.removeprefix("~/") / GLOBAL_SKILL_NAME


__all__ = (
    "GLOBAL_SKILL_NAME",
    "HARNESS_GLOBAL_SKILLS",
    "HarnessGlobalSkill",
    "SHARED_SKILLS_DIR",
    "global_skill_for_harness",
    "copy_path",
    "shared_skill_dir",
)
