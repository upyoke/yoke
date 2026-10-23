# Yoke — Project Rules
<!-- BEGIN GENERATED: field-note-directive -->
File a field note each time a recipe, help text or refusal is wrong or missing, or you spot a bug outside your task — before moving on. If you already filed the same problem, add `--correlation-id <that note's id>`:
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
<!-- END GENERATED: field-note-directive -->

<!-- BEGIN YOKE MANAGED BLOCK -->
<!-- Managed by `yoke project install`. Everything between the BEGIN and END markers is overwritten on refresh — do not edit it here. Your own content outside the markers is always preserved. -->
These rules bind now. Rule loading per harness: `.yoke/docs/agents/harness-discovery.md`.

## Standing authority

A Yoke skill that says auto-X authorizes X: do it without asking. Security rules and prohibited
actions still hold.

## Writing to users
<!-- BEGIN GENERATED: user-writing -->
Each message to the user is one or two sentences unless they ask for more. Write short, literal, active sentences without idioms; natural questions are fine. Use plain words for ideas and exact names for fields, commands and files; explain an unfamiliar name briefly where it first appears. Never write a bare number or ID: say what it is, e.g. "#411 (soft-launch PR)". When the user must decide, ask one decision at a time, most important first, each with your recommendation. Teach only what they need now, show the action before explaining it, and point to the exact place for more. The sentence limit covers narration; required instructions, recipes and evidence stay complete.
<!-- END GENERATED: user-writing -->

## Always

- Work in the lane your work claim covers. Never implement on main or use `--no-worktree`
  unless the user asks.
- Path claims never narrow scope: every required file stays in the item and its File Budget.
  The 350-line authored-file limit always holds.
- Run Yoke operations through `yoke <subcommand>`, never runtime API, client or HTTP calls.
  SQL is diagnostic only: `yoke db read "SELECT ..."`, with `<>`. Never print secrets.
- Each shell call starts fresh: use absolute paths and `git -C`. Capture long output once.
- Check a name, path, flag or live state against evidence before you assert it. Use full
  commit hashes and the bare integer `item_id`.
- Name code for what it does now. Names and prose carry no work-item, plan, phase or criterion
  ids (`PREFIX-12`, `AC-7`) unless they are runtime data.
- Commit every completed change; leave no dirty tree. Commit before CI; never push by hand.
  Update the surface that owns a changed behavior; delete text the change makes wrong.
- Iterate with `yoke watch pytest --impacted main --bounded`; the attached QA case owns the
  full run.
- A verification failure in this item belongs to this item.
  Update a test this item's change made stale; never weaken a behavior assertion to pass.
- Never discard changes, stashes or files without user authority.
- Write items only through typed `yoke` item commands. Never hand-edit generated views.
- File bugs through `/yoke idea` or a field note. Find the root cause; describe a failure as a
  system gap, never as agent error.
- On a watcher wake, tell the user in one sentence what changed (item, PR, failing test), or
  nothing. Fleet mail is only for blockers, conflicts, red gates, decisions, results.
- After compaction, reload the current-phase skill. Answer a user message before you continue. Never
  enter plan mode on your own.

## Operation homes

Before an operation, read its home in `.yoke/docs/agents/rules/`, then the command's `--help`.
Live recipes: `yoke packets render --role main_agent`.

- `code-and-cli.md`: code, naming, teaching. `shell-and-cli.md`: shell and CLI calls.
- `lanes-and-claims.md`: lanes, project scope, overlaps, destructive operations.
- `item-writes.md`: item writes, Progress Log, board. `databases.md`: schema or bulk data.
- `verification.md`: tests, QA, CI. `delivery.md`: deployment runs and delivery.
- `release-roles.md`: release identity. `packs.md`: Packs, credentials, infrastructure.
- `architecture-model.md`: architecture model and cross-cutting dependencies.
- `claude-sessions.md`, `claude-long-commands.md`: Claude hooks, identity, long commands.

## Architecture Model

Read the `architecture_model` payload before dependency changes; `architecture_impact: uncertain`
blocks readiness.

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
<!-- KEEP IN SYNC: hand-copied, identical in the yoke and platform repos. Edit both together. -->
## Control-Plane Authority — Hard Rule (this installation)
- Automate; record root causes (subagents if nontrivial) before recovery.
- **Non-testing control-plane operations run on prod** for every target environment: releases, receipts, deployment-run and delivery records, GitHub relays. **Stage only tests the live control plane:** nothing real routes through or depends on it; `stage-db-admin` holds disposable rehearsal state only.
- **Use `--env prod` for routine operations.** `prod-db-admin` is only for `db read`, migration rehearsal, driving prod's self-deploy and an explicit admin merge; anything else refuses `use_https_env`.
- **Yoke releases ship Platform** (via its pin). Merged PLAT items ride the next Yoke release; start a Platform flow only when none is in flight.
- **Platform's database (`yoke_platform`) is read-only here:** `yoke --env platform-prod-registry-db-admin db read "SELECT ..."` (stage: `platform-stage-registry-db-admin`; connections: `yoke env list`).
# Yoke Repo Internals
Manifest: `runtime/harness/manifest-schema.md`. Author install-bundle docs under
`docs/public/`, run
`yoke dev run -- python3 -m yoke_core.domain.install_bundle_tree_sync sync --target-root <checkout>`
and commit every changed path together.

## Source-Dev Doctrine
Read [`docs/source-dev-doctrine.md`](docs/source-dev-doctrine.md) before tests, releases,
renders, deploys, preflight or cleanup. Run lane commands as `yoke dev run -- <command>`.
`--local` is only a small targeted check expected to finish in about one minute;
uncommitted work does not justify a slow local run. Watchers inject xdist `-n auto`. The attached QA case runs the full gate
`yoke watch pytest -- runtime/api/ runtime/harness/ tests/` once.
Lint: `yoke dev ruff-changed --base <ref>`.
