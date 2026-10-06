---
name: yoke
description: "Your operating system for software delivery — where harnesses report for duty."
argument-hint: "{subcommand} [args]"
---

# Yoke — Command Router

This skill routes to subcommands and teaches nothing else. Parse the arguments,
then read the one file the subcommand owns.

## Routing Instructions

1. **Extract the subcommand** from the arguments — it is the first word (e.g., `shepherd`, `conduct`). A colon-separated form like `/yoke:conduct` or `yoke:shepherd` names the subcommand after the colon.
2. **Plan-mode guard.** Apply the generated classification below.
3. **Read the instruction file** at `.agents/skills/yoke/{subcommand}/SKILL.md` using the Read tool, and follow it, passing any remaining arguments as that subcommand's arguments. Each entrypoint is a short router: it names the one phase file to read next. Do not pre-read a command's phase files.
4. **If the subcommand is missing, unknown, or `help`,** read [`help/SKILL.md`](help/SKILL.md) and follow it. That file is the single command reference — operator commands, local terminal helpers, item commands that need a harness session, internal sub-skills, and the typical flows. Do not restate it here or anywhere else.

## Subcommands

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

Three routing facts that decide where a request goes before any file is read:

- `/yoke onboard [--project P] [--run-id RUN]` makes an already-wired project
  execution-ready — strategy docs, execution profile, Packs, hosting,
  environments, a gated first deploy, and seeded first work. Machine and
  project **wire-up** is the terminal `yoke setup` wizard instead; this skill
  never reimplements it.
- `/yoke simulate PREFIX-N` and `/yoke simulate --system` are a harness slash
  skill only — there is no terminal `yoke simulate` adapter.
- `/yoke steer [STRATEGY-DOC-SLUG]` resolves an omitted slug to `CURRENT-PLAN`
  rather than asking; an explicitly supplied slug always wins.
- `/yoke refine PREFIX-N` critiques artifacts with no worktree and no code
  edits; `/yoke polish PREFIX-N` finishes implementation inside an existing
  worktree. Neither substitutes for the other.
- `/yoke implement PREFIX-N` is the stage skill for the segment a workflow
  binds to `implement` (issue implementation entry through review); it takes
  no target argument. Stage writes use `yoke lifecycle transition`.
- `/yoke idea --workflow issue|epic|blitz|task {title}` files new work through
  the skill path. Filing without executing is the terminal
  `yoke dash TITLE INSTRUCTION` / `yoke task TITLE INSTRUCTION` pair.
