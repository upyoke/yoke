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

```

<!-- BEGIN GENERATED: skill-registry -->
Skill metadata is generated from `yoke_contracts.skill_registry`.
Change that source and run `yoke dev run -- python3 -m
yoke_core.tools.render_skill_registry_inline --target-root CHECKOUT`.

| Skill | Kind | Session mode | Autonomy | Purpose |
|---|---|---|---|---|
| `/yoke blitz PREFIX-N` | stage | `blitz` | autonomous execution | execute document-led work |
| `/yoke charge` | orchestrator | `charge` | autonomous execution | select runnable frontier work |
| `/yoke conduct PREFIX-N` | stage | `conduct` | autonomous execution | execute generated task lanes |
| `/yoke curate` | utility | `curate` | follow skill decision gates | curate the Ouroboros learning log |
| `/yoke dash PREFIX-N` | stage | `dash` | autonomous execution | execute instruction-led work |
| `/yoke doctor [project]` | utility | `doctor` | follow skill decision gates | run health checks |
| `/yoke feed` | orchestrator | `feed` | follow skill decision gates | refresh frontier work |
| `/yoke help` | utility | `operator` | follow skill decision gates | show command reference |
| `/yoke idea` | utility | `idea` | follow skill decision gates | file a backlog item |
| `/yoke implement PREFIX-N` | stage | `implement` | autonomous execution | implement and review an item |
| `/yoke models` | utility | `operator` | follow skill decision gates | publish model catalog revisions |
| `/yoke onboard [--project P]` | orchestrator | `operator` | follow skill decision gates | make a wired project execution-ready |
| `/yoke polish PREFIX-N` | stage | `polish` | autonomous execution | review and finish implementation |
| `/yoke refine PREFIX-N` | stage | `refine` | follow skill decision gates | critique and improve item artifacts |
| `/yoke resync` | utility | `operator` | follow skill decision gates | detect and repair GitHub drift |
| `/yoke shepherd PREFIX-N` | stage | `shepherd` | autonomous execution | execute the pinned planning interval |
| `/yoke simulate PREFIX-N \| --system` | utility | `simulate` | follow skill decision gates | trace integration paths; no terminal `yoke simulate` adapter |
| `/yoke steer [STRATEGY-DOC-SLUG]` | orchestrator | `steer` | autonomous execution | staff work from a strategy document; omitted slug defaults to `CURRENT-PLAN` |
| `/yoke strategize` | orchestrator | `strategize` | follow skill decision gates | review project strategy |
| `/yoke usher PREFIX-N [--dry-run]` | stage | `usher` | autonomous execution | merge and deliver an item |
| `/yoke wrapup` | utility | `wrapup` | follow skill decision gates | wrap up the session |
<!-- END GENERATED: skill-registry -->

```text
LOCAL TERMINAL HELPERS
 yoke setup
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
 /yoke idea --workflow issue|epic|blitz|task {title}
  Select the workflow when filing new work; `/yoke blitz` executes document-led work.
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
 yoke models lookup MODEL_ID / get / validate / diff / publish / revisions / restore
  Sourced effective-dated catalog reads, review, and publication. Use `/yoke models` for the full recipe.

WORKFLOW ROUTING
 yoke workflows item get PREFIX-N --json
  Read the item's pinned workflow version, live stage, and next bound skill.
 yoke workflows version get <workflow> <version> --json
  Read that immutable definition's stages, transitions, gates, and skill bindings.
  The binding's half-open interval owns the live stage; its through_stage_id
  is the next command and claim handoff. Use the returned next_skill_id.
  Lifecycle flows come from this definition, including the release wait.

DEPENDENCY INSPECTION
 Authoritative dependency data lives in the item_dependencies table.
 yoke items dependency list PREFIX-N
 Show the full dependency graph for an item (both directions).
 Dependencies are enforced by implement (before implementing) and usher (before merge).
 usher --dry-run shows the dependency edges driving merge order.

For full documentation, see README.md
```
