"""Render skill metadata through the existing generated-block mechanism.

Run with --target-root CHECKOUT; --check verifies the same registered family
at commit time without writing. Skill membership is authored only in contracts.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from yoke_contracts.skill_registry import SKILLS
from yoke_core.domain.agents_render_workspace import resolve_target_root_for_cli
from yoke_core.tools.generated_block_render import (
    RenderResult,
    format_drift_summary,
    render_blocks,
)

SLUG = "skill-registry"
INVENTORY = (
    ".agents/skills/yoke/SKILL.md",
    "docs/public/reference/commands.md",
    "docs/harness-bootstrap.md",
    ".agents/skills/yoke/help/SKILL.md",
)


def _names(skills) -> str:
    return " · ".join(f"`{skill.entrypoint}`" for skill in skills)


def content_for_path(path: str) -> str:
    public = [skill for skill in SKILLS if skill.kind != "internal"]
    lines = [
        "Skill metadata is generated from `yoke_contracts.skill_registry`.",
        "Change that source and run `yoke dev run -- python3 -m",
        "yoke_core.tools.render_skill_registry_inline --target-root CHECKOUT`.",
        "",
    ]
    if path == INVENTORY[0]:
        lines.extend(
            [
                "Operator: " + _names(public),
                "",
                "Internal: "
                + " · ".join(
                    f"[{skill.id}]({skill.path or skill.id}/SKILL.md)"
                    for skill in SKILLS
                    if skill.kind == "internal"
                ),
                "",
                "**Plan-mode guard.** Classify the selected skill before dispatch:",
                "",
                "- Execute-class commands: "
                + _names(skill for skill in SKILLS if skill.plan_mode == "exit")
                + ".",
                "- "
                + _names(skill for skill in SKILLS if skill.plan_mode == "idea_write")
                + " write paths exit plan mode.",
                "- "
                + _names(skill for skill in SKILLS if skill.plan_mode == "refine_gate")
                + " exits after Gate 0.",
                "- Planning-class commands: "
                + _names(skill for skill in SKILLS if skill.produces_tasks)
                + " planning and "
                + _names(skill for skill in SKILLS if skill.plan_mode == "refine_gate")
                + " Gate 0 preserve plan mode.",
                "- Every other skill preserves plan mode.",
                "- On exit, call `ExitPlanMode` when available and emit: `Plan mode auto-exited — Yoke work item is the plan.` Harnesses without that tool emit the same note and continue.",
            ]
        )
    else:
        lines.extend(
            [
                "| Skill | Kind | Session mode | Autonomy | Purpose |",
                "|---|---|---|---|---|",
            ]
        )
        for skill in public:
            autonomy = (
                "autonomous execution"
                if skill.autonomous
                else "follow skill decision gates"
            )
            lines.append(
                f"| `{skill.display.replace(chr(124), chr(92) + chr(124))}` | {skill.kind} | `{skill.session_mode}` | {autonomy} | {skill.description} |"
            )
    return "\n".join(lines) + "\n"


def render(target_root: Path, *, check: bool = False) -> RenderResult:
    return render_blocks(
        target_root,
        slug=SLUG,
        inventory=INVENTORY,
        content_for_path=content_for_path,
        check=check,
    )


def format_drift_summary_for_family(result: RenderResult, *, check: bool) -> str:
    return format_drift_summary(
        result,
        check=check,
        family_label="skill registry",
        repair_command="yoke dev run -- python3 -m yoke_core.tools.render_skill_registry_inline --target-root CHECKOUT",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-root")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    result = render(resolve_target_root_for_cli(args.target_root), check=args.check)
    print(format_drift_summary_for_family(result, check=args.check), end="")
    return int(not result.ok or bool(result.changed) and args.check)


if __name__ == "__main__":
    raise SystemExit(main())
