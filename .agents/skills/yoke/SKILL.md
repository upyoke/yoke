---
name: yoke
description: "Your operating system for software delivery — where harnesses report for duty."
argument-hint: "{subcommand} [args]"
---

# Yoke — Command Router

Apply the plan-mode guard, then read `{subcommand}/SKILL.md` and pass the remaining arguments. Unknown: [help](help/SKILL.md).

<!-- BEGIN GENERATED: skill-registry -->
Skill metadata is generated from `yoke_contracts.skill_registry`.
Change that source and run `yoke dev run -- python3 -m
yoke_core.tools.render_skill_registry_inline --target-root CHECKOUT`.

Operator: `/yoke blitz` · `/yoke charge` · `/yoke conduct` · `/yoke curate` · `/yoke dash` · `/yoke doctor` · `/yoke feed` · `/yoke help` · `/yoke idea` · `/yoke implement` · `/yoke models` · `/yoke onboard` · `/yoke polish` · `/yoke refine` · `/yoke resync` · `/yoke shepherd` · `/yoke simulate` · `/yoke steer` · `/yoke strategize` · `/yoke usher` · `/yoke wrapup`

Internal: [amend](amend/SKILL.md) · [approve](approve/SKILL.md) · [implementing](implement/implementing/SKILL.md)

**Plan-mode guard.** Classify the selected skill before dispatch:

- Execute-class commands: `/yoke blitz` · `/yoke conduct` · `/yoke dash` · `/yoke implement` · `/yoke polish` · `/yoke usher`.
- `/yoke idea` write paths exit plan mode.
- `/yoke refine` exits after Gate 0.
- Planning-class commands: `/yoke shepherd` planning and `/yoke refine` Gate 0 preserve plan mode.
- Every other skill preserves plan mode.
- On exit, call `ExitPlanMode` when available and emit: `Plan mode auto-exited — Yoke work item is the plan.` Harnesses without that tool emit the same note and continue.
<!-- END GENERATED: skill-registry -->
