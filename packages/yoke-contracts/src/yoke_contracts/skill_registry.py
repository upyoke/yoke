"""Canonical skill semantics shared by runtime and teaching renderers.

Bindings own stages. This inventory owns skills, not historical workflow pins.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Skill:
    id: str
    kind: Literal["stage", "orchestrator", "utility", "internal"]
    session_mode: str
    autonomous: bool
    description: str
    arguments: str = ""
    plan_mode: Literal["exit", "preserve", "refine_gate", "idea_write"] = "preserve"
    implementation: bool = False
    produces_tasks: bool = False
    path: str = ""

    @property
    def entrypoint(self) -> str:
        return f"/yoke {self.id}"

    @property
    def display(self) -> str:
        return f"{self.entrypoint} {self.arguments}".rstrip()

    @property
    def body_path(self) -> str:
        return f".agents/skills/yoke/{self.path or self.id}/SKILL.md"


SKILLS: tuple[Skill, ...] = (
    Skill(
        "amend", "internal", "shepherd", False, "amend a synced task graph", "PREFIX-N"
    ),
    Skill(
        "approve", "internal", "operator", False, "record a deployment approval", "RUN"
    ),
    Skill(
        "blitz",
        "stage",
        "blitz",
        True,
        "execute document-led work",
        "PREFIX-N",
        "exit",
        True,
    ),
    Skill("charge", "orchestrator", "charge", True, "select runnable frontier work"),
    Skill(
        "conduct",
        "stage",
        "conduct",
        True,
        "execute generated task lanes",
        "PREFIX-N",
        "exit",
        True,
    ),
    Skill("curate", "utility", "curate", False, "curate the Ouroboros learning log"),
    Skill(
        "dash",
        "stage",
        "dash",
        True,
        "execute instruction-led work",
        "PREFIX-N",
        "exit",
        True,
    ),
    Skill("doctor", "utility", "doctor", False, "run health checks", "[project]"),
    Skill("feed", "orchestrator", "feed", False, "refresh frontier work"),
    Skill("help", "utility", "operator", False, "show command reference"),
    Skill(
        "idea", "utility", "idea", False, "file a backlog item", plan_mode="idea_write"
    ),
    Skill(
        "implement",
        "stage",
        "implement",
        True,
        "implement and review an item",
        "PREFIX-N",
        "exit",
        True,
    ),
    Skill(
        "implementing",
        "internal",
        "implement",
        True,
        "kick off implementation",
        path="implement/implementing",
    ),
    Skill("models", "utility", "operator", False, "publish model catalog revisions"),
    Skill(
        "onboard",
        "orchestrator",
        "operator",
        False,
        "make a wired project execution-ready",
        "[--project P]",
    ),
    Skill(
        "polish",
        "stage",
        "polish",
        True,
        "review and finish implementation",
        "PREFIX-N",
        "exit",
    ),
    Skill(
        "refine",
        "stage",
        "refine",
        False,
        "critique and improve item artifacts",
        "PREFIX-N",
        "refine_gate",
    ),
    Skill("resync", "utility", "operator", False, "detect and repair GitHub drift"),
    Skill(
        "shepherd",
        "stage",
        "shepherd",
        True,
        "execute the pinned planning interval",
        "PREFIX-N",
        produces_tasks=True,
    ),
    Skill(
        "simulate",
        "utility",
        "simulate",
        False,
        "trace integration paths",
        "PREFIX-N | --system",
    ),
    Skill(
        "steer",
        "orchestrator",
        "steer",
        True,
        "staff work from a strategy document",
        "[STRATEGY-DOC-SLUG]",
    ),
    Skill("strategize", "orchestrator", "strategize", False, "review project strategy"),
    Skill(
        "usher",
        "stage",
        "usher",
        True,
        "merge and deliver an item",
        "PREFIX-N [--dry-run]",
        "exit",
    ),
    Skill("wrapup", "utility", "wrapup", False, "wrap up the session"),
)
SKILLS_BY_ID = {skill.id: skill for skill in SKILLS}
STAGE_SKILL_IDS = frozenset(skill.id for skill in SKILLS if skill.kind == "stage")
IMPLEMENTATION_SKILL_IDS = frozenset(
    skill.id for skill in SKILLS if skill.implementation
)
TASK_PRODUCING_SKILL_IDS = frozenset(
    skill.id for skill in SKILLS if skill.produces_tasks
)
SKILL_SESSION_MODES = frozenset(skill.session_mode for skill in SKILLS)
