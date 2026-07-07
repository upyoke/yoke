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
   - Execute-class commands (`advance`, `conduct`, `usher`, `polish`, `idea` write paths, and `refine` write paths after Gate 0) automatically call `ExitPlanMode` when the tool exists, with this note: `Plan mode auto-exited — Yoke ticket is the plan.`
   - Planning-class commands (`shepherd plan`, `plan`, and `refine` Gate 0 critique/planning) honor plan mode and continue without auto-exit.
   - Harnesses without an `ExitPlanMode` tool continue normally after emitting the same one-line note.
3. **Read the instruction file** at `.agents/skills/yoke/{subcommand}/SKILL.md` using the Read tool. If the file is missing, show the command reference instead of inventing a replacement.
   For setup, the entry point is the `yoke onboard` Textual wizard, which opens on the deployment-destination picker (this machine's local universe / a team server / upyoke.com), walks the destination's sign-in lane plus GitHub, Project, and Review, and previews every write before applying (`--local` / `--connect URL` route non-interactively). To install or repair a project's local operating layer afterward, use `yoke project install`. The standalone per-mode commands `yoke project create`, `yoke project import`, and `yoke onboard project` script a single project source non-interactively. Verify with `yoke status`; `yoke dev setup` is the explicit source-dev/admin add-on.
   Use `/yoke onboard-project` only for harness-side agentic adoption after deterministic install.
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
| `/yoke onboard-project` | Harness-side agentic project adoption after deterministic install |
| `/yoke idea {title}` | Capture a new backlog item |
| `/yoke shepherd YOK-N` | Drive item through quality-gated lifecycle to ready |
| `/yoke conduct YOK-N` | Engineer/Tester loop for a single item |
| `/yoke usher [YOK-N]` | Merge and deploy passed items |
| `/yoke doctor [project]` | Health checks and diagnostics (`--fix` for auto-repair) |
| `/yoke freeze YOK-N` | Freeze a backlog item |
| `/yoke thaw YOK-N` | Thaw a frozen item |
| `/yoke block YOK-N "<reason>"` | Block an item (preserves lifecycle status) |
| `/yoke unblock YOK-N` | Clear an item's blocked flag |
| `/yoke resync` | Detect and repair drift between local and GitHub |
| `/yoke curate` | Curate the Ouroboros learning log |
| `/yoke wrapup` | Structured session wrap-up |
| `/yoke refine YOK-N` | Critique and improve item artifacts (no worktree, no code) |
| `/yoke advance YOK-N implementation` | Issue implementation entry: create or re-enter the worktree |
| `/yoke polish YOK-N` | Review and finish implementation in existing worktree |
| `/yoke help` | Show this command reference |

### Local Terminal Helpers

These are operator-facing `yoke` CLI helpers that run directly in a terminal without a harness session.

| Command | Description |
|---|---|
| `yoke onboard` | Full-screen Textual machine setup wizard (destination picker, sign-in or local universe, GitHub, Project, Review); `--local` / `--connect URL` pick the destination, `--yes` for a silent apply |
| `yoke project create` / `yoke project import` / `yoke onboard project` | Standalone per-mode project source and binding flows (the wizard's Project step covers these interactively) |
| `yoke project install [CHECKOUT]` | Install or repair the project-local Yoke operating layer |
| `yoke status` | Verify machine, env, credential, and checkout bindings |
| `yoke dev setup [CHECKOUT]` | Explicit Yoke source-dev/admin setup |
| `yoke board art variant create --ascii\|--mixed\|--image PATH` | Generate, preview, and optionally apply `.yoke/board-art` variants |
| `yoke project snapshot sync [CHECKOUT]` | Scan committed git tree state and sync authoritative path snapshots |
| `yoke git pre-commit` | Run the installed pre-commit gate entrypoint. |
| `yoke git post-commit` | Run the installed post-commit path snapshot sync entrypoint. |

### Internal Sub-skills
`/yoke advance` is dual-classified: `implementation` is operator-facing for issues; other targets remain internal lifecycle transitions.

| Command | Called by | Description |
|---|---|---|
| `/yoke advance YOK-N [status]` | conduct, usher, do/loop, routed dispatch | Internal advance targets other than `implementation` |
| `/yoke merge {epic-id}` | usher | Sequential PR + merge per branch |
| `/yoke approve YOK-N` | usher | Approve a deployment stage awaiting human approval |
| `/yoke amend {epic-id}` | conduct | Add, split, reassign, or remove tasks after sync |
| `/yoke plan {epic-id}` | shepherd, conduct | Architect planning: task decomposition or lightweight plan |
| `/yoke simulate {epic-id}` | conduct | Trace cross-task paths for integration gaps |
