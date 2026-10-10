# Yoke — Project Rules
<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

<!-- BEGIN YOKE MANAGED BLOCK -->
<!-- Managed by `yoke project install`. Everything between the BEGIN and END markers is overwritten on refresh — do not edit it here. Your own content outside the markers is always preserved. -->
Native loading: `.yoke/docs/reference/harness-discovery.md`. Standing rules bind now; operation homes bind before acting.

## Standing authority

**Skill says auto-X → do auto-X, no asking.** Invoking a Yoke skill authorizes its autonomous steps; harness confirmation defaults do not apply. Security and prohibited actions always hold. Unsure: reread the skill.

## Project Scoping

One item has one project. Cross-project changes require linked companion items; a changed contract requires its consumer companion and evidence the real consumer built against the exact candidate. Ask when the target is ambiguous.

## Worktree Discipline

Work claims authorize lanes. Never implement on main or use `--no-worktree` without explicit user instruction. Prepare the registered lane immediately after claim/read/minimal survey, from verified-current upstream. Preserve divergence; unreadable upstream blocks. Route from the live pinned workflow's half-open binding; never invent stages.

## Path Claims — Hard Rule

File Budget and path claims are independent axes from `workflows.item.get`'s `effective_policies`. The 350-line authored-file limit (`yoke_core.domain.file_line_check`) always holds. Claimed paths do not narrow scope: Every required file stays in the item; never omit, descope, or rewrite away a required file. Claims are coordination/dependency/blocking facts. Read `lanes-and-claims.md` before resolving any overlap; runtime coordination decisions route to Refine.

Authoring agents attest independent overlaps with `coordination_only`; ordered edits require directional `activation` evidence. Only the dependent waits. Unattested overlap stays incompatible; claims coordinate physical files, including symlink targets.

### yoke CLI

Use registered function ids through `yoke <subcommand>`, never direct runtime API/client/HTTP recipes. Postgres owns control-plane state, never constructed paths/DSNs or lane DB files. Diagnostic SQL: `yoke db read "SELECT ..."`, with `<>`; no write SQL. Missing mutations escalate. Never print secrets or dump settings.

Reusable capabilities ship as immutable Packs; config stays in DB/project policy, credentials capability-owned. Hold `DEPLOY:<project>` before creating/executing runs. Merge before release; hosted flows own exact commits and proof. Remote changes originate locally.

## Before acting: operation homes

Read the applicable `.yoke/docs/reference/agent-rules/` home first, then the operation's `--help`. Live schemas/recipes: `yoke packets render --role main_agent`.

- `code-and-cli.md`: code, naming, shell/CLI, serving floors, simplify and teaching.
- `lanes-and-claims.md`: preparation, scope, overlaps, routing, destruction and authority.
- `item-writes.md`: item creation, typed structured writes, Progress Log and board.
- `databases.md`: schema/bulk-data changes, governed rehearsal and DB authority.
- `verification.md`: tests, QA, CI, captures and health checks.
- `delivery.md`: Packs, credentials, deployment claims, runs and receipts.
- `architecture-model.md`: model changes and cross-cutting dependencies.
- `claude-sessions.md`: Claude hooks, watcher waiting and session recovery.

## Code Conventions

Verify capabilities/state against live evidence before asserting them. Resolve refs to bare integer `item_id` and full commit hashes; never expand abbreviations. Purge retired terms; historical provenance goes in commits/archive. Prefer Python for stateful helpers.

**Codebase-reader naming:** Assume future readers of the codebase will NOT have planning artifacts. Planning artifacts are scaffolding; name live code by current function, purpose, mechanics. FILE and DIRECTORY names, symbols and prose never carry work-item/epic/plan/milestone/phase/stage/tier/slice/track/wave/batch/field-note provenance or acceptance criterion/functional requirement/spec identifiers (`PREFIX-1234`, `AC-7`, `FR-3`, §7), except runtime/domain data and fixtures. A directory must explain its purpose to a repository reader.

## Simplify — three-axis doctrine

Apply reuse, quality and efficiency: name an existing surface, keep scope minimal, justify new infrastructure. Pull future concepts forward; read the code home for stage weights.

Commit every completed change; no dirty tree between tasks. Update all affected docs. Permanent migrations are never deleted. Simulate with real values before execution; verify afterward.

## Verification Failure Ownership

Current-item verification failures belong to the current item; a future item or planned path claim is not a waiver. Fix failures here unless a live conflict or explicit operator waiver applies; preserve failure/rerun evidence. Use dependency and claim reconciliation before override. Do not use `path-claim-override` for a planned future claim; irreducible live collisions require a live steering seat covering the project; route the override through `yoke say --steering` and read `yoke claims path override --help`.

### Bash tool calls

Capture non-trivial commands once; use watchers for long runs. Iterate with `yoke watch pytest --impacted main --bounded`; the attached QA case owns the final full execution. Continue yielded handles until exit, never relaunch or manually poll. Read verification before local interruption. Shell variables reset per call; Claude's sticky cwd may persist. Use absolute paths, `git -C`, `python3`, quoted patterns and `rg --files`. Commit before CI; workers never push by hand.

Never discard changes/stashes/files without sanctioned or user authority. Read destruction rules first; `git stash push -u -m "reason" -- <paths>` keeps the message before the separator.

## Structured Item Writes

Never edit generated views without an ingest command; `yoke board rebuild` explicitly refreshes the board. Item writes are typed registered functions. Progress Log entries are current-state checkpoints via `items.progress_log.append`; task-graph fields stay untouched with `generated_children=none`. Work-item entry surfaces use allowed workflows (`/yoke idea`: `harness_skill`); Architect decomposes.

File bugs through `/yoke idea`, `yoke dash` or field-notes; never harness task suggestions. Find root cause first; describe failures systemically, never as "agent error/mistake." After compaction reload the current-phase skill. Answer mid-sequence user messages before continuing. Prefer inline chat; the item is the plan. Insufficient plans escalate; never enter plan mode on your own.

Harness settings route hooks through `yoke hook evaluate <event>`; Python owns them. Read the installed release's product harness manifest before stating capabilities.

## Governed DB Mutation

Read `databases.md` before schema or bulk-data changes; it owns restore points, serving floors, canonical serializers, idempotency and every live universe's rehearsal. Boot applies; items author and rehearse.

## Architecture Model

Read the authoritative payload before model/dependency changes. Use its gateways; declare `architecture_impact`. `uncertain` blocks readiness.

## Command Output — Hard Rule
<!-- BEGIN GENERATED: read-recipe -->
Want part of an answer? Ask the narrow question — every read has a shape that serves it.

```text
yoke <command> <arguments>      # the routine answer, already scoped
yoke items get PREFIX-N status  # the fields you name
tail -80 <raw-capture>          # the capture a watcher prints, once it exits
```
<!-- END GENERATED: read-recipe -->
<!-- END YOKE MANAGED BLOCK -->
