# Slash Commands Reference

<!-- yoke:breadcrumbs -->
[Yoke](../index.md) > [Agents](index.md) > Commands
<!-- /yoke:breadcrumbs -->

Skills live at `.agents/skills/yoke/{name}/SKILL.md`; native discovery or the
harness adapter invokes the same procedure. `yoke_contracts.skill_registry`
owns ids, arguments, modes, autonomy and dispatch classification. The registry
below is generated; edit its owner and use its stated renderer, never the table.
Target harness manifests own available tools/hooks. Source maintainers use
`docs/harness-bootstrap.md` and `docs/hook-parity-map.md` for those contracts.

The universal authored-file limit is 350 lines, enforced where files are
readable by pre-commit, survey and Doctor. Active work-claim rows authorize
registered lanes. File Budget and path claims are
independent effective workflow policies; parity applies only when both are
enabled. Turning either off does not waive the file limit. Read
`yoke check file-line --help` for its classified source checks.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Find the right operation

```text
yoke --help
yoke items --help
yoke items get --help
```

Each level lists immediate children. Command help owns its recipe and options.
For agent help, ask `/yoke help` a topic. [Help and replies](../cli/help.md) explains
labeled results, complete saved evidence and deliberate machine formats.

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
| `/yoke dash "spec" \| {PREFIX-N}` | stage | `dash` | autonomous execution | execute spec-led work |
| `/yoke doctor [project] [--fix] [--file path]` | utility | `doctor` | follow skill decision gates | run health checks |
| `/yoke feed [--no-new-items] [PREFIX-N ...] [--model MODEL]` | orchestrator | `feed` | follow skill decision gates | refresh frontier work |
| `/yoke help` | utility | `wait` | follow skill decision gates | show command reference |
| `/yoke idea [--dry-run] [--workflow issue\|epic\|blitz\|task] {title}` | utility | `idea` | follow skill decision gates | file a backlog item |
| `/yoke implement {PREFIX-N} [--no-worktree] [--force] [--qa-bypass]` | stage | `implement` | autonomous execution | implement and review an item |
| `/yoke models lookup MODEL_ID \| get \| validate \| diff \| publish \| revisions \| restore \| level-proposal` | utility | `wait` | follow skill decision gates | publish model catalog revisions and propose level changes |
| `/yoke onboard [--project P] [--run-id RUN]` | orchestrator | `wait` | follow skill decision gates | adopt existing work and reach the first item done |
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
| `yoke dash TITLE SPEC` / `yoke task TITLE SPEC` | File direct work after resolving execution instructions; Dash owns a lane, Task is laneless and merge-free |
| `yoke board art variant create` | Create and preview board-art variants |
| `yoke project snapshot sync [CHECKOUT]` | Sync committed path inventory |
| `yoke git pre-commit` / `yoke git post-commit` | Installed verification/snapshot hooks |
| `yoke dev path-snapshot-prewarm` | Source-dev/admin inventory prewarm |

Read each operation's `--help` for payload and authority before acting.

## Delivery skill boundaries

Read the item's pin, then follow the binding containing its live stage:

```text
yoke workflows item get PREFIX-N
yoke workflows version get {workflow} {version}
```

The half-open interval owns entry, forward edges and handoff. Never route from
a remembered workflow name or stage sequence. A handoff starts the next skill
with its fresh claim; it does not extend the preceding skill's authority.
The canonical procedure is `.agents/skills/yoke/{skill}/SKILL.md`; its phase
map selects depth before that action. [Lifecycle](../reference/lifecycle.md) owns gates.

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
[typed item operations](../reference/db-reference/functions-items.md), verify stored results
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
GitHub polling or unchanged failed-train retries. The shared selector reads the
caller's manifest wake capability: a native idle-wake primitive gets the
background subscription; no or unverified idle wake gets one foreground command.
Rely on a later completion message only when the selector chose background-wake. See
[queue recovery](../github/merge-queue-landings.md) and `usher/merge.md` before merging.

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
[task operations](../reference/db-reference/functions-tasks.md) and the Amend skill.

### simulate

Trace plan or integration paths with real values, including failure paths.
The Simulate router selects phase and dispatch inputs. Compressed integration
preserves preliminary verdict and bounded selective verification; complete
reports and attempt/identity receipts remain durable. `simulate/autofix-loop.md`
owns the Architect repair loop, capped at three passes: direct use asks before
fixes/re-simulation, `--auto-fix` accepts them. Conduct uses its defined amend
cycle for remaining code gaps. `--system` is read-only consistency review;
persist its report and file actionable work, never auto-fix from that report.

## Related

- [Maintenance commands and context](maintenance-commands.md)
