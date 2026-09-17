---
name: amend
description: Add, split, reassign, or remove tasks after sync. Re-verifies overlap and updates GitHub.
argument-hint: "{epic-id}"
---

# Internal sub-skill -- called by conduct. Not operator-facing.

# /yoke amend {epic-id}

Modify an epic's tasks after the initial sync. Use when you need to add
new tasks, split existing ones, reassign worktrees, or remove tasks.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Arguments

- `{epic-id}` — The item's PREFIX-N identifier (e.g., `PREFIX-N`). The item
  must have tasks in the `epic_tasks` table.

## Philosophy

**Be the giant.** We stand on inherited shoulders; leave a leg up for
the next agent. Amend changes the execution blueprint after work has
already started, so every split, reassignment, or removal must leave
crisp task boundaries and an unambiguous next step — a checkpoint, not
a restated history.

**No such thing as "agent error."** If tasks need to be split or
moved, frame the cause as a system correction — missing task
boundaries, stale overlap assumptions, or new information discovered
during execution — not as blame on the Engineer or Architect.

**Artifact writes are work writes.** Work item/spec/body edits,
epic-task body/metadata mutations, worktree-plan rewrites, dependency
edits, File Budget adjustments, path-claim amendments, and GitHub
issue-body edits are shared coordination state — the calling session
must hold the work claim on the epic before any of these mutations.
Session ids returned by `who-claims` identify the coordination holder;
they are not a capability token that re-authorizes amend writes from
another session.

## Phase map — read one file, at the phase it governs

| Phase | You are here when | Read before acting |
|---|---|---|
| Amend | The conduct caller just invoked this sub-skill | [`steps.md`](steps.md) |
| — Look up a function id | You need an amend operation's exact envelope | [`surfaces.md`](surfaces.md) |

## Start

Read [`steps.md`](steps.md) and follow it.
