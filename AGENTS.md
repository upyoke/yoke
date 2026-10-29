# Yoke — Project Rules
<!-- BEGIN YOKE MANAGED BLOCK -->
<!-- Managed by `yoke project install`. Everything between the BEGIN and END markers is overwritten on refresh — do not edit it here. Your own content outside the markers is always preserved. -->
<!-- BEGIN GENERATED: feedback-directive -->
Report problems with Yoke to Yoke, and problems with your projects to your own universe, before moving on. In your universe, link repeat evidence with `--correlation-id <first note id>`.
yoke feedback --to yoke --category failed --evidence 'Yoke recipe failed: ...'
yoke feedback --to universe --category observation --evidence 'Project finding: ...'
<!-- END GENERATED: feedback-directive -->
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
- Use absolute paths and `git -C` in every shell call. Capture long output once.
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
- A failure the system should have handled is a system gap: before any manual recovery,
  root-cause it (a subagent if nontrivial) and file a field note or `/yoke idea`.
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

## Yoke repository
Run lane commands as `yoke dev run -- <command>`. Before tests, releases, renders, deploys,
control-plane writes, preflight or cleanup, read [`docs/source-dev-doctrine.md`](docs/source-dev-doctrine.md).

Here, Yoke problems are project problems; file them with
`yoke feedback --to universe --category failed --evidence "..."`.
