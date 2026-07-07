---
name: help
description: Show the Yoke command reference and quick-start guide.
---

# /yoke help

Display the Yoke command reference.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug not worth a ticket, file a field-note immediately — before retrying, before moving on.
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
 /yoke feed [--no-new-tickets] Direct-mode: maintain frontier dependency graph and optionally materialize new work from strategy layer
 /yoke strategize Direct-mode: guided SML review (research, propose, approve)
 /yoke onboard-project Harness-side agentic project adoption after deterministic install
 /yoke idea {title} Capture a new backlog item
 /yoke shepherd YOK-N Drive an epic through quality-gated planning to planned
 /yoke conduct YOK-N Engineer/Tester loop for a single epic
 /yoke usher [YOK-N] Merge and deploy implemented/release items
 /yoke doctor [project] Health checks and diagnostics (--fix for auto-repair)
 /yoke freeze YOK-N Freeze a backlog item
 /yoke thaw YOK-N Thaw a frozen item
 /yoke block YOK-N "<reason>" Block an item (preserves lifecycle status)
 /yoke unblock YOK-N Clear an item's blocked flag
 /yoke resync Detect and repair drift between local and GitHub
 /yoke curate Curate the Ouroboros learning log
 /yoke wrapup Structured session wrap-up
 /yoke refine YOK-N Critique and improve item artifacts (no worktree)
 /yoke advance YOK-N implementation Issue implementation entry: create or re-enter the worktree
 /yoke polish YOK-N Review and finish implementation in existing worktree

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
 yoke board art variant create --ascii
  Generate, preview, and optionally apply .yoke/board-art variants.
  Use `--mixed` or `--image PATH` for the other variant families.
  Runs directly in a terminal; no harness session is required.

AUTONOMOUS MODE
 /yoke do -> decision engine picks the best next action
 /yoke charge -> directly pick up and begin work
 /yoke feed -> maintain frontier graph + materialize work from strategy layer
 /yoke strategize -> refresh + research + propose + approve SML changes

TYPICAL FLOW
 1. /yoke idea "my feature" -> YOK-N in backlog
 2. /yoke refine YOK-N -> issue idea/refinement -> refined-idea
 3. /yoke advance YOK-N implementation -> issue worktree -> reviewed-implementation
 4. /yoke polish YOK-N -> reviewed-implementation -> implemented
 5. /yoke usher YOK-N -> merge -> deploy -> done

 Epics use /yoke shepherd and /yoke conduct for their planning and implementation loop.

DEPENDENCY INSPECTION
 Authoritative dependency data lives in the item_dependencies table.
 yoke shepherd dependency-list YOK-N
 Show the full dependency graph for an item (both directions).
 Dependencies are enforced by advance (before implementing) and usher (before merge).
 usher --dry-run shows the dependency edges driving merge order.

INTERNAL (called by orchestration commands, not operator-facing)
 advance targets other than implementation, merge, approve, amend, plan, simulate

For full documentation, see README.md
```
