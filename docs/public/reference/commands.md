# Slash Commands Reference

Skills live at `.agents/skills/yoke/{name}/SKILL.md`; native discovery or the
harness adapter invokes the same procedure. `yoke_contracts.skill_registry`
owns ids, arguments, modes, autonomy and dispatch classification. The registry
below is generated; edit its owner and use its stated renderer, never the table.
Target harness manifests own available tools/hooks. Source maintainers use
`docs/harness-bootstrap.md` and `docs/hook-parity-map.md` for those contracts.

The universal authored-file limit is 350 lines, enforced where files are
readable by pre-commit, survey and Doctor. File Budget and path claims are
independent effective workflow policies; parity applies only when both are
enabled. Turning either off does not waive the file limit. Read
`yoke check file-line --help` for its classified source checks.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Operator Commands

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

## Local Terminal Helpers

These are operator CLI helpers, distinct from lifecycle slash commands:

| Command | Purpose |
|---|---|
| `yoke dash TITLE INSTRUCTION` / `yoke task TITLE INSTRUCTION` | File direct work after resolving execution instructions; Dash owns a lane, Task is laneless and merge-free |
| `yoke board art variant create` | Create and preview board-art variants |
| `yoke project snapshot sync [CHECKOUT]` | Sync committed path inventory |
| `yoke git pre-commit` / `yoke git post-commit` | Installed verification/snapshot hooks |
| `yoke dev path-snapshot-prewarm` | Source-dev/admin inventory prewarm |

Read each operation's `--help` for payload and authority before acting.

## Delivery skill boundaries

Read the item's pin, then follow the binding containing its live stage:

```text
yoke workflows item get PREFIX-N
yoke workflows version get WORKFLOW VERSION
```

The half-open interval owns entry, forward edges and handoff. Never route from
a remembered workflow name or stage sequence. A handoff starts the next skill
with its fresh claim; it does not extend the preceding skill's authority.
The canonical procedure is `.agents/skills/yoke/{skill}/SKILL.md`; its phase
map selects depth before that action. [Lifecycle](lifecycle.md) owns gates.

### idea

File structured work with one target project, pinned workflow and allowed typed
entry surface. Resolve applicable instructions, title limits, duplicate work,
Pack reuse and cross-project companions before creation. Persist complete scope,
normalized ACs and dependencies; verify the receipt and linked GitHub sync.
Use the Idea phase map for inference and additive body writes.

### refine

Review authoritative structured artifacts for scope, interfaces, cleanup,
failure/recovery, testability and architecture impact. Reconcile claims and
independent File Budget policy without omitting required paths. Write through
[typed item operations](db-reference/functions-items.md), verify stored results
and advance only the pin's declared edge. Successful Refine advances status;
it edits artifacts, not code.

### shepherd

Execute the pinned planning segment and generated-task policy. Conditional PM
and design, Architect, Simulator and Boss gates persist their declared verdicts;
retries stay bounded at three attempts. A skipped design verdict skips only
design. Resume from verdict history and live artifacts, not a copied stage map.
Progress Log holds current execution state; generated planning fields retain
their defined authoritative roles. Follow the Shepherd phase map before each
gate and read fresh item state at handoff.

### implement

Enter or re-enter the pinned Implement interval in the same session. Entry
preflight takes the claim, activates paths and creates/reuses the item's lane
before deeper investigation or edits. QA seeding and project context precede
audit/discovery. Complete implementation, attached QA and every declared review
write through handoff. Capture success with no passing verdict is not QA proof.
Entry flags and evidence-only handling belong to the Implement entry owner;
do not bypass production gates or create a session boundary for a worktree.

### conduct

Execute generated task lanes through Engineer/Tester loops, then integration
simulation. Conduct orchestrates; implementation and verification stay with
the dispatched roles. Read evaluated dependencies, dispatch freshness and
durable submission receipts before advancing. Required paths stay in scope
through conflicts. Do not auto-waive blocking QA. Chain state is durable and
resumable; the current pin determines the handoff.

The Conduct router owns entry, dispatch, simulation and recovery. Retry limits
are taught in `conduct/retry-budgets.md`; flags remain defined by the registry
and entry owner. Large diffs are externalized, preserving complete evidence.
The shared Tester template owns normal/minimal/retry/fix input contracts.

### polish

Resolve the registered implementation lane set, review its diff against item
artifacts, apply the scoped simplify pass and make finishing fixes in place.
Verify changed roots, current QA, cleanup/residue and file sizes; commit each
completed change. Follow `skill_bindings` from `from_stage_id` to
`through_stage_id`, using `yoke lifecycle transition` on each declared edge.
Report `next_skill_id` at handoff through its fresh command entrypoint.
A successful review with no changes is valid;
an actual failure needs its repair and rerun evidence.

### usher

Collect authorized items, compute dependency order and follow the current
Usher phase map: collect, plan, merge, deploy, finalize. Dry-run reports only;
normal invocation carries its authorized autonomous mandate. Deployment
approval, QA waivers and operator decisions retain their explicit gates.
An approval uses the registered decision/run action and exact candidate
evidence; telemetry or a manual stage write never substitutes for it.

Queue projects require the PR's exact combined merge-group proof. A headless
landing handoff preserves claim and evidence for the control-plane notice;
re-enter the same merge boundary after wake. Other callers use the manifest
selected streaming/wait command and keep its handle through exit. No local
GitHub polling or unchanged failed-train retries. See
[queue recovery](merge-queue-landings.md) and `usher/merge.md` before merging.

Deploy-free routes complete without a run. Managed routes hold the deployment
coordination claim, preserve composition/candidate/QA identity and drive their
selected flow; a failed selected-flow delivery cannot become skip-deploy proof.
Resume retained partial state through Usher and its named recovery. Never
change `current_stage` or fabricate success to skip a failure. Finalize records
actual landing, delivery and QA; done remains pipeline-owned.

### approve

Record the human decision on the exact paused run. Validate the current gate,
candidate and approver authority through the registered surface, retaining
history. A failed stage is not an approval opportunity. Follow the Approve
skill and returned run recovery before resuming.

### amend

Add, split, reassign or remove generated tasks through the existing typed task
family and progress notes. Reverify overlap, dependencies, numbering and lane
assignment; preserve the complete required graph. See
[task operations](db-reference/functions-tasks.md) and the Amend skill.

### simulate

Trace plan or integration paths with real values, including failure paths.
The Simulate router selects phase and dispatch inputs. Compressed integration
preserves preliminary verdict and bounded selective verification; complete
reports and attempt/identity receipts remain durable. `simulate/autofix-loop.md`
owns the Architect repair loop, capped at three passes: direct use asks before
fixes/re-simulation, `--auto-fix` accepts them. Conduct uses its defined amend
cycle for remaining code gaps. `--system` is read-only consistency review;
persist its report and file actionable work, never auto-fix from that report.

## Operator maintenance and steering

### charge

Read the evaluated runnable frontier, show ranked reasons and adapter
classification, apply its operator selection gate and dispatch the bound skill.
Use the explicit project/scope and WIP policy; no guessed project. Read
[frontier details](charge-frontier.md) before selection.

### feed

Reconcile strategy and frontier facts: leave premature work in strategy,
refresh dependencies, sharpen/split existing work, or materialize stable new
items. Generated edges retain rationale and structured evidence. Feed owns
semantic graph maintenance; ranking, WIP and claims belong to their existing
owners. `--no-new-items` permits analysis/graph refresh without creation.

### strategize

Review the SML against current reality with source-backed research. Follow its
operator checkpoints for refresh, framing, research, proposed strategy changes,
frontier implications and actual tradeoff conflicts. DB strategy rows are
authority; rendered `.yoke/strategy/` files are views. Preserve decision and
checkpoint history. See [strategy](../strategy.md).

### onboard

Make a wired project execution-ready with confirmed strategy/profile, Packs,
explicit test/hosting/database posture, verified delivery defaults and seeded
QA-bound work. Follow its approvals before infrastructure effects. Existing
credentials and host exclusions retain their custody and named refusals.
Machine `yoke setup` and harness onboarding are separate operations.

### doctor

Run applicable health checks with the watcher:

```text
yoke watch doctor -- --full
```

Keep the returned stream through exit. Each check declares project/tree/runtime/
capability scope; N/A names its reason and is neither pass nor omission.
Project-local `.yoke/doctor/` checks join the same report; import failure fails.
`--fix` follows the Doctor skill's repair gates, not blanket change authority.

### resync

Detect linkage, field and body drift between Yoke and GitHub; default is read-only.
Use `--fix` only within its authorized repair scope and verify retained linkage.

### curate

Cluster unreviewed Ouroboros observations, verify code and duplicates, route
actionable work to Dash or a scoped work item and archive handled entries.
Keep actual evidence and reasons; a field-note is not a discovered-work bypass.

### wrapup

Record current unfinished work, holds, blockers, next actions and durable links
in Progress Log; capture learning through Ouroboros. Do not replace active work
with an accumulated essay or a terminal status unsupported by delivery.

### help

Show this command reference and quick-start guidance. `/yoke` without arguments
selects help.

### freeze / thaw

Use `yoke items freeze` / `yoke items thaw` with their `--help`: frozen is an
orthogonal flag, not lifecycle status.

### block / unblock

Use `yoke items block` / `yoke items unblock` with their `--help` for an item's
own reason. Dependency edges own waits on another item; path-claim blocked
state is separate. Forward and closure gates still enforce their obligations.

## Internal Sub-skills

<!-- BEGIN GENERATED: skill-registry-internal -->
Internal skills are generated from `yoke_contracts.skill_registry`.

| Skill body | Purpose |
|---|---|
| `.agents/skills/yoke/amend/SKILL.md` | amend a synced task graph |
| `.agents/skills/yoke/approve/SKILL.md` | record a deployment approval |
| `.agents/skills/yoke/implement/implementing/SKILL.md` | kick off implementation |
<!-- END GENERATED: skill-registry-internal -->

These bodies serve the parent procedure; their existence does not bypass its
claim, binding or approval boundary. The Simulate and Usher phase maps include
support files that are not independent skill bodies.

## Internal Support Artifacts

`shared/tester-dispatch-template.md` is the sole Tester input contract for item,
generated-task, retry and simulation fixes: identity/spec, complete QA roster,
commands, lane, changed files, size-gated diff, ephemeral URL and durable receipt.

## Project Context Loading

Implement loads project context before text audit/discovery. Conduct adds the
project context and test/ephemeral facts to each role dispatch. Use declared
context routing and topic matches; report missing files and only then broaden
exploration. Project ids are universe-local; checkout resolution is environment
scoped. One item targets one project; installed behavior stays project-owned.

## Key Patterns

- Registered function ids and their CLI adapters own state; raw SELECTs are
  diagnostic reads. Operator source-dev break-glass is separate authority.
- Complete structured fields and persisted reviews are authoritative; rendered
  bodies, boards and local strategy files are views.
- Required facts live in durable owners. Events are diagnostic and absence
  proves nothing; a quoted event name is not execution proof.
- [Project install](../projects.md) owns clean/current upstream, generated
  paths, commit/publication, protected-branch PR and named partial-state repair.
  Source-maintainer link/admin setup uses `yoke dev setup`, a distinct
  contributor operation rather than an external-project installation recipe.
- [QA](../qa.md) owns immutable requirements, actual execution, review and
  waivers. A command passing elsewhere cannot replace its selected case.
- Bindings and selected delivery flow determine close-out. Do not use a copied
  progression, scalar terminal write or unsupported skip to claim completion.
