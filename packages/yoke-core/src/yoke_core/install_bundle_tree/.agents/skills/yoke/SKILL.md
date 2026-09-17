---
name: yoke
description: "Your operating system for software delivery — where harnesses report for duty."
argument-hint: "{subcommand} [args]"
---

# Yoke — Command Router

This skill routes to subcommands and teaches nothing else. Parse the arguments,
then read the one file the subcommand owns.

## Routing Instructions

1. **Extract the subcommand** from the arguments — it is the first word (e.g., `plan`, `conduct`). A colon-separated form like `/yoke:conduct` or `yoke:plan` names the subcommand after the colon.
2. **Plan-mode guard.** If plan mode is active, classify the subcommand before dispatch:
   - Execute-class commands (`advance`, `conduct`, `usher`, `polish`, `dash`, `blitz`, `idea` write paths, and `refine` write paths after Gate 0) automatically call `ExitPlanMode` when the tool exists, with this note: `Plan mode auto-exited — Yoke work item is the plan.`
   - Planning-class commands (`shepherd plan`, `plan`, and `refine` Gate 0 critique/planning) honor plan mode and continue without auto-exit.
   - Harnesses without an `ExitPlanMode` tool continue normally after emitting the same one-line note.
3. **Read the instruction file** at `.agents/skills/yoke/{subcommand}/SKILL.md` using the Read tool, and follow it completely, passing any remaining arguments as that subcommand's arguments. Each entrypoint is a short router: it names the one phase file to read next. Do not pre-read a command's phase files.
4. **If the subcommand is missing, unknown, or `help`,** read [`help/SKILL.md`](help/SKILL.md) and follow it. That file is the single command reference — operator commands, local terminal helpers, item commands that need a harness session, internal sub-skills, and the typical flows. Do not restate it here or anywhere else.

## Subcommands

Operator: `/yoke do` · `/yoke charge` · `/yoke feed` · `/yoke strategize` ·
`/yoke steer` · `/yoke onboard` · `/yoke idea` · `/yoke dash` · `/yoke blitz` ·
`/yoke shepherd` · `/yoke conduct` · `/yoke usher` · `/yoke doctor` ·
`/yoke models` · `/yoke resync` · `/yoke curate` · `/yoke wrapup` ·
`/yoke refine` · `/yoke advance` · `/yoke polish` · `/yoke simulate` ·
`/yoke help`

Internal, called by an orchestration command rather than an operator:
`/yoke merge` · `/yoke approve` · `/yoke amend` · `/yoke plan`, plus
`/yoke advance` targets other than `implementation`.

Three routing facts that decide where a request goes before any file is read:

- `/yoke onboard [--project P] [--run-id RUN]` makes an already-wired project
  execution-ready — strategy docs, execution profile, Packs, hosting,
  environments, a gated first deploy, and seeded first work. Machine and
  project **wire-up** is the terminal `yoke onboard` wizard instead; this skill
  never reimplements it.
- `/yoke simulate PREFIX-N` and `/yoke simulate --system` are a harness slash
  skill only — there is no terminal `yoke simulate` adapter.
- `/yoke refine PREFIX-N` critiques artifacts with no worktree and no code
  edits; `/yoke polish PREFIX-N` finishes implementation inside an existing
  worktree. Neither substitutes for the other.
- `/yoke advance PREFIX-N implementation` is the operator-facing Issue
  implementation entry; every other `advance` target is internal.
- `/yoke idea --workflow issue|epic|blitz|task {title}` files new work through
  the skill path. Filing without executing is the terminal
  `yoke dash TITLE INSTRUCTION` / `yoke task TITLE INSTRUCTION` pair.
