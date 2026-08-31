---
name: yoke
description: "Your operating system for software delivery — where harnesses report for duty."
argument-hint: "{subcommand} [args]"
---

# Yoke — Command Router

This skill routes to subcommands. Parse the arguments to determine which subcommand to execute.

## Routing Instructions

1. **Extract the subcommand** from the arguments — it is the first word (e.g., `plan`, `conduct`).
2. **Plan-mode guard.** If plan mode is active, classify the subcommand before dispatch:
   - Execute-class commands (`advance`, `conduct`, `usher`, `polish`, `dash`, `blitz`, `idea` write paths, and `refine` write paths after Gate 0) automatically call `ExitPlanMode` when the tool exists, with this note: `Plan mode auto-exited — Yoke work item is the plan.`
   - Planning-class commands (`shepherd plan`, `plan`, and `refine` Gate 0 critique/planning) honor plan mode and continue without auto-exit.
   - Harnesses without an `ExitPlanMode` tool continue normally after emitting the same one-line note.
3. **Read the instruction file** at `.agents/skills/yoke/{subcommand}/SKILL.md` using the Read tool. If the file is missing, show the command reference instead of inventing a replacement.
   For setup, the entry point is the `yoke onboard` Textual wizard, whose destination picker offers this machine's local universe, an existing team server, guided self-host server setup on this machine, or upyoke.com. Guided self-host setup previews Docker, the loopback URL/port, bundle path, Compose work, and operator-owned networking before writing; it leaves an active owner-only connection and either continues into GitHub/Project or exits with a server handoff. The wizard then walks the destination's connection lane plus GitHub, Project, and Review, and previews every remaining write before applying (`--local` / `--connect URL` route non-interactively). To install or repair a project's local operating layer afterward, use `yoke project install`. The standalone per-mode commands `yoke project create`, `yoke project import`, and `yoke onboard project` script a single project source non-interactively. Verify with `yoke status`; `yoke dev setup` is the explicit source-dev/admin add-on.
   After wire-up, `/yoke onboard` is the harness-side skill that makes the wired project execution-ready — strategy docs, execution profile, Packs, hosting, environments, a gated first deploy, and seeded first work.
4. **Follow those instructions completely**, passing any remaining arguments as that subcommand's arguments.

If the user typed a colon-separated form like `/yoke:conduct` or `yoke:plan`, the part after the colon is the subcommand.

If no subcommand is provided, or the subcommand is `help`, show the command reference below.

## Command Reference

### Operator Commands
| Command | Description |
|---|---|
| `/yoke do` | Autonomous session orchestrator — decision engine picks the next action |
| `/yoke charge` | Direct-mode: pick up next runnable item from the frontier |
| `/yoke feed` | Direct-mode: materialize new work from the strategy layer |
| `/yoke strategize` | Direct-mode: guided SML review (research, propose, approve) |
| `/yoke steer <STRATEGY-DOC-SLUG> [--project P]` | Direct-mode: itemless steering loop over a required strategy doc |
| `/yoke onboard [--project P] [--run-id RUN]` | Make a wired project execution-ready: strategy, profile, Packs, hosting, environments, gated first deploy, seeded work |
| `/yoke idea [--workflow issue\|epic\|blitz\|task] {title}` | Capture a new backlog item; `blitz` for document-led execution, `task` for laneless floor work |
| `/yoke dash "instruction"` or `/yoke dash PREFIX-N` | File and execute instruction-sized work, or resume a Dash |
| `/yoke blitz PREFIX-N` | Execute a refined Blitz from its single linked strategy document |
| `/yoke shepherd PREFIX-N` | Drive item through quality-gated lifecycle to ready |
| `/yoke conduct PREFIX-N` | Engineer/Tester loop for a single item |
| `/yoke usher [PREFIX-N]` | Merge and deploy passed items |
| `/yoke doctor [project]` | Health checks and diagnostics (`--fix` for auto-repair) |
| `/yoke resync` | Detect and repair drift between local and GitHub |
| `/yoke curate` | Curate the Ouroboros learning log |
| `/yoke wrapup` | Structured session wrap-up |
| `/yoke refine PREFIX-N` | Critique and improve item artifacts (no worktree, no code) |
| `/yoke advance PREFIX-N implementation` | Issue implementation entry: create or re-enter the worktree |
| `/yoke polish PREFIX-N` | Review and finish implementation in existing worktree |
| `/yoke simulate PREFIX-N` or `/yoke simulate --system` | Trace integration paths or audit system-wide consistency; harness slash skill only, with no terminal `yoke simulate` adapter |
| `/yoke help` | Show this command reference |

### Local Terminal Helpers

These are operator-facing `yoke` CLI helpers that run directly in a terminal without a harness session.

| Command | Description |
|---|---|
| `yoke onboard` | Full-screen Textual machine setup wizard (local, existing server, guided self-host, or hosted destination; then connection, GitHub, Project, Review); `--local` / `--connect URL` route non-interactively, `--yes` for a silent apply |
| `yoke project create` / `yoke project import` / `yoke onboard project` | Standalone per-mode project source and binding flows (the wizard's Project step covers these interactively) |
| `yoke project install [CHECKOUT]` | Install or repair the project-local Yoke operating layer |
| `yoke status` | Verify machine, env, credential, and checkout bindings |
| `yoke dev setup [CHECKOUT]` | Explicit Yoke source-dev/admin setup |
| `yoke board art variant create --ascii\|--mixed\|--image PATH` | Generate, preview, and optionally apply `.yoke/board-art` variants |
| `yoke project snapshot sync [CHECKOUT]` | Scan committed git tree state and sync authoritative path snapshots |
| `yoke items freeze PREFIX-N` / `yoke items thaw PREFIX-N` | Park an item off the active board, or return it (keeps its lifecycle status). Work that will never resume is `yoke items cancel`. |
| `yoke items cancel PREFIX-N --reason TEXT [--ref PREFIX-M]` | Cancel an item that will never resume (takes the claim; frozen items cancel in one step) |
| `yoke items block PREFIX-N --reason TEXT` / `yoke items unblock PREFIX-N` | Set or clear the blocked flag and reason (keeps its lifecycle status) |
| `yoke git pre-commit` | Run the installed pre-commit gate entrypoint. |
| `yoke git post-commit` | Run the installed post-commit path snapshot sync entrypoint. |

### Internal Sub-skills
`/yoke advance` is dual-classified: `implementation` is operator-facing for issues; other targets remain internal lifecycle transitions.

| Command | Called by | Description |
|---|---|---|
| `/yoke advance PREFIX-N [status]` | conduct, usher, do/loop, routed dispatch | Internal advance targets other than `implementation` |
| `/yoke merge {epic-id}` | usher | Sequential PR + merge per branch |
| `/yoke approve PREFIX-N` | usher | Approve a deployment stage awaiting human approval |
| `/yoke amend {epic-id}` | conduct | Add, split, reassign, or remove tasks after sync |
| `/yoke plan {epic-id}` | shepherd, conduct | Architect planning: task decomposition or lightweight plan |
