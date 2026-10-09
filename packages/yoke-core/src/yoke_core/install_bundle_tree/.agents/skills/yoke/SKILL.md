---
name: yoke
description: "Your operating system for software delivery — where harnesses report for duty."
argument-hint: "{subcommand} [args]"
---

# Yoke — Command Router

Read the selected subcommand's router and follow it.

## Routing Instructions

1. Parse the first word, or the name after a colon (`/yoke:conduct`, `yoke:shepherd`).
2. Apply the generated plan-mode classification below.
3. Read `.agents/skills/yoke/{subcommand}/SKILL.md`, follow its next-phase pointer, and pass remaining arguments. Read phases when reached.
4. Missing, unknown or `help`: follow [`help/SKILL.md`](help/SKILL.md), the sole command reference for operator/local helpers, harness item commands, internal skills and flows.

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

Routing distinctions:

- `/yoke onboard [--project P] [--run-id RUN]` prepares an already-wired project:
  strategy, execution profile, Packs, hosting, environments, gated first deploy
  and seeded work. Terminal `yoke setup` owns machine/project wire-up.
- `/yoke simulate PREFIX-N` and `/yoke simulate --system` are a harness slash
  skill only — there is no terminal `yoke simulate` adapter.
- `/yoke steer [STRATEGY-DOC-SLUG]` defaults an omitted slug to `CURRENT-PLAN`
  without asking; an explicit slug wins.
- `/yoke refine PREFIX-N` critiques artifacts without a worktree/code edits;
  `/yoke polish PREFIX-N` finishes implementation in an existing lane.
- `/yoke implement PREFIX-N` runs the pinned implementation-through-review
  segment without a target argument; stage writes use `yoke lifecycle transition`.
- `/yoke idea --workflow issue|epic|blitz|task {title}` files new work through
  the skill path. Filing without executing is the terminal
  `yoke dash TITLE INSTRUCTION` / `yoke task TITLE INSTRUCTION` pair.
