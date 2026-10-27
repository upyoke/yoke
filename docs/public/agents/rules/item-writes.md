# Writing to items, and the generated board

<!-- yoke:breadcrumbs -->
[Getting started](../../index.md) > [Command and technical reference](../../guide/reference/index.md) > [Agents](../index.md) > [Operation homes](index.md) > Item writes
<!-- /yoke:breadcrumbs -->

## Structured item writes

Every item write is a typed function call; each `yoke items ...` command is its adapter and its
`--help` owns the flags. Function ids: [function families](../../functions/index.md).

- `items.body` is rendered, not stored. Read it with `yoke items get PREFIX-N body`; write the
  structured fields instead.
- Replace a whole field with `items.structured_field.replace` (`spec`, `design_spec`,
  `technical_plan`, `worktree_plan`, `shepherd_caveats`, `test_results`, `deploy_log`). Pass the
  content from a file or stdin.
- Add to a field with `items.structured_field.append_addendum`, `section_upsert` or
  `section_append`. Reading a field into the shell and piping it back is refused.
- Epic task content goes through `workflow_item.epic_task.*`; task notes through
  `workflow_item.epic_progress_note.append`.
- Write `shepherd_caveats` and `worktree_plan` only when the pinned workflow generates
  `epic_tasks`. With `generated_children=none`, use the Progress Log.

## Creating items

- A create names a workflow and its allowed entry surface; `/yoke idea` uses `items.create`
  with `harness_skill`.
- Titles obey the project's `title_max_length`.
- Architect decomposes `epic_tasks`; do not pre-file child items.

## Progress Log

Use `items.progress_log.append` (`yoke items progress-log append --help`). Each entry is a
current-state checkpoint: objective, standing decisions and holds, active work, blockers, next
action, and links to evidence. Do not restate full results or historical status snapshots;
they live in earlier entries and item fields. Keep an entry at or under 4,096 bytes.

Checkpoint unfinished work while you hold its work claim, before a wait, handoff or release.
A terminal item already records its result: skip the final checkpoint, and never reacquire a
claim only to write one.

## Board

`.yoke/BOARD.md` is generated and untracked. Nothing rebuilds it automatically; run
`yoke board rebuild` (see `--help`). Board settings live in the project's `project-policy`
document. A stored document keeps the keys it has; change one with
`yoke projects capability-settings set`.

## Related

- [Operating with agents](../index.md)
- [Agent operation homes](index.md)
