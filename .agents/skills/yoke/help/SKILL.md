---
name: help
description: Show the Yoke command reference and quick-start guide.
---

# /yoke help

Display the Yoke command reference.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Output

Show the following reference:

```
Yoke -- Your operating system for software delivery

COMMANDS
 /yoke do Autonomous orchestrator — decision engine picks next action
 /yoke charge Direct-mode: pick up next runnable item from frontier
 /yoke feed [--no-new-items] Direct-mode: maintain frontier dependency graph and optionally materialize new work from strategy layer
 /yoke strategize Direct-mode: guided SML review (research, propose, approve)
 /yoke steer <STRATEGY-DOC-SLUG> [--project P] Direct-mode: itemless steering loop over a required strategy doc
 /yoke onboard [--project P] [--run-id RUN] Make a wired project execution-ready (strategy, profile, Packs, hosting, envs, gated first deploy, seeded work)
 /yoke idea [--workflow issue|epic|blitz|task] {title} Capture a new backlog item
 /yoke dash "instruction" | PREFIX-N File and execute instruction-sized work, or resume a Dash
 /yoke blitz PREFIX-N Execute a refined Blitz from its single linked strategy document
 /yoke shepherd PREFIX-N Drive an epic through quality-gated planning to planned
 /yoke conduct PREFIX-N Engineer/Tester loop for a single epic
 /yoke usher [PREFIX-N] Merge and deploy implemented/release items
 /yoke doctor [project] Health checks and diagnostics (--fix for auto-repair)
 /yoke resync Detect and repair drift between local and GitHub
 /yoke curate Curate the Ouroboros learning log
 /yoke wrapup Structured session wrap-up
 /yoke refine PREFIX-N Critique and improve item artifacts (no worktree)
 /yoke advance PREFIX-N implementation Issue implementation entry: create or re-enter the worktree
 /yoke polish PREFIX-N Review and finish implementation in existing worktree
 /yoke simulate PREFIX-N | --system Trace integration paths or audit system consistency (harness slash skill; no terminal `yoke simulate` adapter)

LOCAL TERMINAL HELPERS
 yoke onboard
  Machine setup wizard; picks where the Yoke lives (local / team server / upyoke.com).
 yoke project create
  Create a new project/repo and bind it to Yoke.
 yoke project import
  Clone/import an existing repo and bind it to Yoke.
 yoke onboard project
  Bind an existing local checkout after machine setup.
 yoke project install [CHECKOUT]
  Install or repair the project-local Yoke operating layer.
 yoke status
  Verify machine, env, credential, and checkout bindings.
 yoke dev setup [CHECKOUT]
  Explicit Yoke source-dev/admin setup.
 yoke dash TITLE INSTRUCTION / yoke task TITLE INSTRUCTION
  File direct work; Task is the laneless, merge-free alternative to Dash.
 yoke items freeze PREFIX-N / yoke items thaw PREFIX-N
  Park an item off the active board, or return it. Lifecycle status is kept.
  Work that will never resume is `yoke items cancel`, not freeze.
 yoke items cancel PREFIX-N --reason TEXT [--ref PREFIX-M]
  Cancel an item that will never resume. Takes the claim; frozen items cancel in one step.
 yoke items block PREFIX-N --reason TEXT / yoke items unblock PREFIX-N
  Set or clear the blocked flag and its reason. Lifecycle status is kept.
  The command takes the item claim for you; refuses if someone holds it.
 yoke board art variant create --ascii
  Generate, preview, and optionally apply .yoke/board-art variants.
  Use `--mixed` or `--image PATH` for the other variant families.
  Runs directly in a terminal; no harness session is required.

AUTONOMOUS MODE
 /yoke do -> decision engine picks the best next action
 /yoke charge -> directly pick up and begin work
 /yoke feed -> maintain frontier graph + materialize work from strategy layer
 /yoke strategize -> refresh + research + propose + approve SML changes
 /yoke steer SLUG -> itemless steering loop over a required strategy doc

TYPICAL FLOW
 1. /yoke idea "my feature" -> PREFIX-N in backlog
 2. /yoke refine PREFIX-N -> issue idea/refinement -> refined-idea
 3. /yoke advance PREFIX-N implementation -> issue worktree -> reviewed-implementation
 4. /yoke polish PREFIX-N -> reviewed-implementation -> implemented
 5. /yoke usher PREFIX-N -> merge -> deploy -> done

 Epics use /yoke shepherd and /yoke conduct for their planning and implementation loop.

 DASH FLOW
 /yoke dash "fix the focused behavior" -> file, execute, verify, merge, record evidence

 BLITZ FLOW
 1. /yoke idea --workflow blitz "my document-led plan" -> Blitz at idea
 2. /yoke refine PREFIX-N -> link exactly one execution strategy document -> refined-idea
 3. /yoke blitz PREFIX-N -> execute slices -> reconcile document -> done + archive linked document

DEPENDENCY INSPECTION
 Authoritative dependency data lives in the item_dependencies table.
 yoke items dependency list PREFIX-N
 Show the full dependency graph for an item (both directions).
 Dependencies are enforced by advance (before implementing) and usher (before merge).
 usher --dry-run shows the dependency edges driving merge order.

INTERNAL (called by orchestration commands, not operator-facing)
 advance targets other than implementation, merge, approve, amend, plan

For full documentation, see README.md
```
