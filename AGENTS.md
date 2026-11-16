# Yoke — Project Rules
<!-- BEGIN YOKE MANAGED BLOCK -->
<!-- Managed by `yoke project install`. Everything between the BEGIN and END markers is overwritten on refresh — do not edit it here. Your own content outside the markers is always preserved. -->
<!-- BEGIN GENERATED: feedback-directive -->
Report problems with Yoke to Yoke, and problems with your projects to your own universe, before moving on. In your universe, link repeat evidence with `--correlation-id <first note id>`.
yoke feedback --to yoke --category failed --evidence 'Yoke recipe failed: ...'
yoke feedback --to universe --category observation --evidence 'Project finding: ...'
<!-- END GENERATED: feedback-directive -->
Yoke tracks this project's work as items and carries each one through claims, lanes,
verification and delivery. `yoke --help` lists its commands. Docs live in `.yoke/docs/`;
the judgment rules no command can check are in `.yoke/docs/agents/rules.md`.

## Rules

- Run Yoke operations through `yoke <subcommand>`, not the runtime API, client or HTTP.
  Use `yoke db read "SELECT ..."` only for diagnosis. Never print secrets.
- When a command refuses, follow the fix it names.
- Anything Yoke should have done automatically but didn't is a Yoke defect: before any
  manual recovery, root-cause it with a subagent and file feedback. Never report a workaround as routine.
- File every operator decision as a decision request and raise it in chat; route through
  steering when a seat is live; never edit a filed question: replace it with
  `yoke decision-requests ask --replaces ID`.
- Commit every completed change; leave no dirty tree. Commit before CI; never push by hand.
- A verification failure in this item belongs to this item; never weaken a behavior assertion to pass.
- Never discard changes, stashes or files you did not create without user authority.
- Work in the lane your work claim covers. Do not implement on main or use `--no-worktree`
  unless the user asks.
- Keep git-tracked files within the project's `file_line_limit` (`.yoke/project.config`).
- Write items only through typed `yoke` item commands.
- When the user names a plan (e.g. `MASTER-PLAN`), read it with `yoke strategy doc get SLUG`; it is not an item.
- Iterate with `yoke watch pytest --impacted main --bounded`; the item's attached QA case owns
  the full run.
- A Yoke skill that says auto-X authorizes X: do it without asking. Security rules still hold.

## Writing to users
<!-- BEGIN GENERATED: user-writing -->
Keep each message to one or two short, plain sentences unless the user asks for more; required instructions, recipes and evidence stay complete. Use exact names for fields, commands and files. Never write a bare number or ID: say what it is, e.g. "#411 (soft-launch PR)". Ask one decision at a time, most important first, with your recommendation.
<!-- END GENERATED: user-writing -->
Record a chat answer with `yoke decision-requests resolve <request id> <option id>`.

## Architecture Model

Read the `architecture_model` payload before you change dependencies. An item whose
`architecture_impact` is `uncertain` is not ready.

## Reading command output
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

Contrary to the routing guidance shipped to all projects above, Yoke problems in this
repository are project problems. Send them to this universe with
`yoke feedback --to universe --category failed --evidence "..."`.
