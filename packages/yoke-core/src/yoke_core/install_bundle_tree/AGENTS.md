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
- Work in the lane your work claim covers. Do not implement on main or use `--no-worktree`
  unless the user asks.
- Keep each authored file at 350 lines or fewer.
- Write items only through typed `yoke` item commands.
- Iterate with `yoke watch pytest --impacted main --bounded`; the item's attached QA case owns
  the full run.
- A Yoke skill that says auto-X authorizes X: do it without asking. Security rules still hold.

## Writing to users
<!-- BEGIN GENERATED: user-writing -->
Keep each message to one or two short, plain sentences unless the user asks for more; required instructions, recipes and evidence stay complete. Use exact names for fields, commands and files. Never write a bare number or ID: say what it is, e.g. "#411 (soft-launch PR)". Ask one decision at a time, most important first, with your recommendation.
<!-- END GENERATED: user-writing -->
File each decision with `yoke decision-requests ask` and also ask in chat. Record a chat
answer with `yoke decision-requests resolve <request id> <option id>`.

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
