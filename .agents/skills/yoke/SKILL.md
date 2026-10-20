---
name: yoke
description: "Your operating system for software delivery — where harnesses report for duty."
argument-hint: "{subcommand} [args]"
---

# Yoke — Command Router

<!-- BEGIN GENERATED: field-note-directive -->
File a field note each time a recipe, help text or refusal is wrong or missing, or you spot a bug outside your task — before moving on. If you already filed the same problem, add `--correlation-id <that note's id>`:
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
<!-- END GENERATED: field-note-directive -->

Apply the plan-mode guard, then read `{subcommand}/SKILL.md` and pass the remaining arguments. Unknown: [help](help/SKILL.md).

<!-- BEGIN GENERATED: skill-registry -->
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
