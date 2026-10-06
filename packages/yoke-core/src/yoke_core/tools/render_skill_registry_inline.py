"""Render skill metadata through the existing generated-block mechanism.

Run with --target-root CHECKOUT; --check verifies the same registered family
at commit time without writing. Skill membership is authored only in contracts.
"""

from __future__ import annotations

import argparse
import dataclasses
from pathlib import Path

from yoke_contracts.skill_registry import SKILLS
from yoke_core.domain.agents_render_workspace import resolve_target_root_for_cli
from yoke_core.domain.json_helper import dumps_compact
from yoke_core.domain.workspace_authority import (
    assert_target_under_session_work_authority,
)
from yoke_core.tools.generated_block_render import (
    FileRenderOutcome,
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
INTERNAL_INVENTORY = INVENTORY[1:3]
ARGUMENT_HINT_NOTICE = (
    "# argument-hint is generated from yoke_contracts.skill_registry."
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


def internal_content_for_path(path: str) -> str:
    lines = [
        "Internal skills are generated from `yoke_contracts.skill_registry`.",
        "",
        "| Skill body | Purpose |",
        "|---|---|",
    ]
    lines.extend(
        f"| `{skill.body_path}` | {skill.description} |"
        for skill in SKILLS
        if skill.kind == "internal"
    )
    return "\n".join(lines) + "\n"


def _render_argument_hints(target_root: Path, *, check: bool) -> RenderResult:
    outcomes = {"changed": [], "unchanged": [], "missing_files": []}
    errors = []
    for skill in SKILLS:
        path = target_root / skill.body_path
        if not path.exists():
            outcomes["missing_files"].append(
                FileRenderOutcome(skill.body_path, "missing_file")
            )
            continue
        original = path.read_text(encoding="utf-8")
        lines = original.splitlines(keepends=True)
        if not lines or lines[0].strip() != "---" or "---\n" not in lines[1:]:
            errors.append(
                f"{skill.body_path}: expected YAML frontmatter before generating argument-hint"
            )
            continue
        end = lines.index("---\n", 1)
        header = [
            line
            for line in lines[1:end]
            if not line.startswith("argument-hint:")
            and line.rstrip() != ARGUMENT_HINT_NOTICE
        ]
        header.extend(
            [
                ARGUMENT_HINT_NOTICE + "\n",
                "argument-hint: " + dumps_compact(skill.arguments) + "\n",
            ]
        )
        rewritten = "".join([lines[0], *header, *lines[end:]])
        changed = rewritten != original
        outcomes["changed" if changed else "unchanged"].append(
            FileRenderOutcome(skill.body_path, "rendered" if changed else "unchanged")
        )
        if changed and not check:
            assert_target_under_session_work_authority(path)
            path.write_text(rewritten, encoding="utf-8")
    return RenderResult(
        tuple(outcomes["changed"]),
        tuple(outcomes["unchanged"]),
        (),
        tuple(outcomes["missing_files"]),
        tuple(errors),
    )


def render(target_root: Path, *, check: bool = False) -> RenderResult:
    public = render_blocks(
        target_root,
        slug=SLUG,
        inventory=INVENTORY,
        content_for_path=content_for_path,
        check=check,
    )
    internal = render_blocks(
        target_root,
        slug=SLUG + "-internal",
        inventory=INTERNAL_INVENTORY,
        content_for_path=internal_content_for_path,
        check=check,
    )
    hints = _render_argument_hints(target_root, check=check)
    return RenderResult(
        **{
            field.name: getattr(public, field.name)
            + getattr(internal, field.name)
            + getattr(hints, field.name)
            for field in dataclasses.fields(RenderResult)
        }
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
