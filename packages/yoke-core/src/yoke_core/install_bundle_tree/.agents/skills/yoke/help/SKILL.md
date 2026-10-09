---
name: help
description: Show the Yoke command reference and quick-start guide.
# argument-hint is generated from yoke_contracts.skill_registry.
argument-hint: ""
---

# /yoke help

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Output

Show this registry and reference:

<!-- BEGIN GENERATED: skill-registry -->
Skill metadata is generated from `yoke_contracts.skill_registry`.
Change that source and run `yoke dev run -- python3 -m
yoke_core.tools.render_skill_registry_inline --target-root CHECKOUT`.

| Skill | Kind | Session mode | Autonomy | Purpose |
|---|---|---|---|---|
| `/yoke blitz {PREFIX-N}` | stage | `blitz` | autonomous execution | execute document-led work |
| `/yoke charge [--dry-run] [--item PREFIX-N] [--project P] [--wip-cap N]` | orchestrator | `charge` | autonomous execution | select runnable frontier work |
| `/yoke conduct PREFIX-N [--max-attempts N] [--no-chain]` | stage | `conduct` | autonomous execution | execute generated task lanes |
| `/yoke curate (no arguments)` | utility | `curate` | follow skill decision gates | curate the Ouroboros learning log |
| `/yoke dash "instruction" \| {PREFIX-N}` | stage | `dash` | autonomous execution | execute instruction-led work |
| `/yoke doctor [project] [--fix] [--file path]` | utility | `doctor` | follow skill decision gates | run health checks |
| `/yoke feed [--no-new-items] [PREFIX-N ...] [--model MODEL]` | orchestrator | `feed` | follow skill decision gates | refresh frontier work |
| `/yoke help` | utility | `wait` | follow skill decision gates | show command reference |
| `/yoke idea [--dry-run] [--workflow issue\|epic\|blitz\|task] {title}` | utility | `idea` | follow skill decision gates | file a backlog item |
| `/yoke implement {PREFIX-N} [--no-worktree] [--force] [--qa-bypass]` | stage | `implement` | autonomous execution | implement and review an item |
| `/yoke models lookup MODEL_ID \| get \| validate \| diff \| publish \| revisions \| restore \| level-proposal` | utility | `wait` | follow skill decision gates | publish model catalog revisions and propose level changes |
| `/yoke onboard [--project P] [--run-id RUN]` | orchestrator | `wait` | follow skill decision gates | make a wired project execution-ready |
| `/yoke polish {PREFIX-N}` | stage | `polish` | autonomous execution | review and finish implementation |
| `/yoke refine {PREFIX-N}` | stage | `refine` | follow skill decision gates | critique and improve item artifacts |
| `/yoke resync [--fix]` | utility | `wait` | follow skill decision gates | detect and repair GitHub drift |
| `/yoke shepherd {PREFIX-N}` | stage | `shepherd` | autonomous execution | execute the pinned planning interval |
| `/yoke simulate {epic-ref} [--auto-fix] \| --system` | utility | `simulate` | follow skill decision gates | trace integration paths; no terminal `yoke simulate` adapter |
| `/yoke steer [STRATEGY-DOC-SLUG] [--project P ...]` | orchestrator | `steer` | autonomous execution | staff work from a strategy document; omitted slug defaults to `CURRENT-PLAN` |
| `/yoke strategize [--model MODEL]` | orchestrator | `strategize` | follow skill decision gates | review project strategy |
| `/yoke usher PREFIX-N [PREFIX-N ...] [--dry-run] [--merge-only] [--deploy-only] [--resume PREFIX-N]` | stage | `usher` | autonomous execution | merge and deliver an item |
| `/yoke wrapup (no arguments)` | utility | `wrapup` | follow skill decision gates | wrap up the session |
<!-- END GENERATED: skill-registry -->

```text
LOCAL TERMINAL HELPERS
 yoke setup
  Machine setup: local, team server or upyoke.com.
 yoke project create
  Create and bind a project/repo.
 yoke project import
  Clone/import and bind a repo.
 yoke onboard project
  Bind a local checkout after setup.
 yoke project install [CHECKOUT]
  Install/repair the project-local operating layer.
 yoke status
  Verify machine/env/credential/checkout bindings.
 yoke dev setup [CHECKOUT]
  Explicit Yoke source-dev/admin setup.
 yoke dash TITLE INSTRUCTION / yoke task TITLE INSTRUCTION
  File direct work; Task is laneless and merge-free.
 /yoke idea --workflow issue|epic|blitz|task {title}
  Select the filing workflow; `/yoke blitz` executes document-led work.
 yoke items freeze PREFIX-N / yoke items thaw PREFIX-N
  Park/return an item, preserving lifecycle status. Cancel work that will never resume.
 yoke items cancel PREFIX-N --reason TEXT [--ref PREFIX-M]
  Takes the claim; frozen items cancel in one step.
 yoke items block PREFIX-N --reason TEXT / yoke items unblock PREFIX-N
  Set/clear blocked flag/reason, preserving lifecycle. Takes the claim; refuses another holder.
 yoke board art variant create --ascii
  Generate/preview/optionally apply .yoke/board-art variants.
  Use `--mixed` or `--image PATH` for the other variant families.
  Terminal-only; no harness session required.
 yoke models lookup MODEL_ID / get / validate / diff / publish / revisions / restore
  Sourced effective-dated catalog reads/review/publication; full recipe: `/yoke models`.

WORKFLOW ROUTING
 yoke workflows item get PREFIX-N --json
  Read pinned workflow/version, live stage and next bound skill.
 yoke workflows version get <workflow> <version> --json
  Read immutable stages/transitions/gates/skill bindings. The half-open binding
  owns the live stage; through_stage_id is the command/claim handoff. Use returned
  next_skill_id. The definition owns lifecycle flows, including the release wait.

DEPENDENCY INSPECTION
 Authority: item_dependencies.
 yoke items dependency list PREFIX-N
  Full graph, both directions; enforced before implementation and merge.
  /yoke usher --dry-run shows dependency-driven merge order.

For full documentation, see README.md
```
