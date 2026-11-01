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
    autonomous: bool
    description: str
    arguments: str = ""
    plan_mode: Literal["exit", "preserve", "refine_gate", "idea_write"] = "preserve"
    implementation: bool = False
    produces_tasks: bool = False
    path: str = ""
    startup_order: int | None = None

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
        "amend",
        "internal",
        False,
        "amend a synced task graph",
        "{epic-ref}",
    ),
    Skill(
        "approve",
        "internal",
        False,
        "record a deployment approval",
        'RUN-ID [--note "..."]',
    ),
    Skill(
        "blitz",
        "stage",
        True,
        "execute document-led work",
        "{PREFIX-N}",
        "exit",
        True,
    ),
    Skill(
        "charge",
        "orchestrator",
        True,
        "select runnable frontier work",
        "[--dry-run] [--item PREFIX-N] [--project P] [--wip-cap N]",
    ),
    Skill(
        "conduct",
        "stage",
        True,
        "execute generated task lanes",
        "PREFIX-N [--max-attempts N] [--no-chain]",
        "exit",
        True,
    ),
    Skill(
        "curate",
        "utility",
        False,
        "curate the Ouroboros learning log",
        "(no arguments)",
    ),
    Skill(
        "dash",
        "stage",
        True,
        "execute spec-led work",
        '"spec" | {PREFIX-N}',
        "exit",
        True,
    ),
    Skill(
        "doctor",
        "utility",
        False,
        "run health checks",
        "[project] [--fix] [--file path]",
    ),
    Skill(
        "feed",
        "orchestrator",
        False,
        "refresh frontier work",
        "[--no-new-items] [PREFIX-N ...] [--model MODEL]",
    ),
    Skill("help", "utility", False, "show command reference", ""),
    Skill(
        "idea",
        "utility",
        False,
        "file a backlog item",
        "[--dry-run] [--workflow issue|epic|blitz|task] {title}",
        plan_mode="idea_write",
        startup_order=0,
    ),
    Skill(
        "implement",
        "stage",
        True,
        "implement and review an item",
        "{PREFIX-N} [--no-worktree] [--force] [--qa-bypass]",
        "exit",
        True,
        startup_order=2,
    ),
    Skill(
        "implementing",
        "internal",
        True,
        "kick off implementation",
        "",
        path="implement/implementing",
    ),
    Skill(
        "models",
        "utility",
        False,
        "publish model catalog revisions and propose level changes",
        "lookup MODEL_ID | get | validate | diff | publish | revisions | restore"
        " | level-proposal",
    ),
    Skill(
        "onboard",
        "orchestrator",
        False,
        "plan dashes and hand off to steer",
        "[--project P] [--run-id RUN]",
    ),
    Skill(
        "polish",
        "stage",
        True,
        "review and finish implementation",
        "{PREFIX-N}",
        "exit",
        startup_order=3,
    ),
    Skill(
        "refine",
        "stage",
        False,
        "critique and improve item artifacts",
        "{PREFIX-N}",
        "refine_gate",
        startup_order=1,
    ),
    Skill(
        "resync",
        "utility",
        False,
        "detect and repair GitHub drift",
        "[--fix]",
    ),
    Skill(
        "shepherd",
        "stage",
        True,
        "execute the pinned planning interval",
        "{PREFIX-N}",
        produces_tasks=True,
    ),
    Skill(
        "simulate",
        "utility",
        False,
        "trace integration paths; no terminal `yoke simulate` adapter",
        "{epic-ref} [--auto-fix] | --system",
    ),
    Skill(
        "steer",
        "orchestrator",
        True,
        "staff work from a strategy document; omitted slug defaults to `CURRENT-PLAN`",
        "[STRATEGY-DOC-SLUG] [--project P ...]",
    ),
    Skill(
        "strategize",
        "orchestrator",
        False,
        "review project strategy",
        "[--model MODEL]",
    ),
    Skill(
        "usher",
        "stage",
        True,
        "merge and deliver an item",
        "PREFIX-N [PREFIX-N ...] [--dry-run] [--merge-only] [--deploy-only] [--resume PREFIX-N]",
        "exit",
        startup_order=4,
    ),
    Skill(
        "wrapup", "utility", False, "wrap up the session", "(no arguments)"
    ),
)
SKILLS_BY_ID = {skill.id: skill for skill in SKILLS}
STAGE_SKILL_IDS = frozenset(skill.id for skill in SKILLS if skill.kind == "stage")
IMPLEMENTATION_SKILL_IDS = frozenset(
    skill.id for skill in SKILLS if skill.implementation
)
TASK_PRODUCING_SKILL_IDS = frozenset(
    skill.id for skill in SKILLS if skill.produces_tasks
)
