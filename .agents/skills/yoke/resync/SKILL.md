---
name: resync
description: Detect and repair drift between local backlog items and their GitHub issues. Default mode is detect-only (read-only); use --fix for auto-repair.
argument-hint: "[--fix]"
---

# /yoke resync

Detect and repair drift between local backlog items (DB) and their corresponding GitHub issues. Reports mismatches in title, status labels, priority labels, type labels, frozen labels, blocked labels, and body content.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug not worth a ticket, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Arguments

- `--fix` — Detect drift and automatically repair all fixable mismatches. Without this flag, the command is read-only.

## Philosophy

**Be the giant.** We stand on inherited shoulders; leave a leg up for the next agent by making this artifact cold-start complete. A drift report should tell the operator exactly what diverged, what is safe to repair, and what still needs judgment.

**No silent repair stories.** If resync changes state, the report should make that history explicit so later sessions do not have to infer whether drift was detected, ignored, or repaired.

## Steps

1. **Run the sanctioned resync command:**

 Determine the mode based on arguments:

 - **Default (no flags):** Run in detect-only mode:
 ```
 yoke resync
 ```

 - **With `--fix`:** Run in fix mode:
 ```
 yoke resync --fix
 ```

 Capture the full stdout output (the drift report).

2. **Display the drift report:**

 Show the complete output to the user. The report includes:
 - Summary of items scanned and mismatches found
 - Per-item drift details (field, local value, GitHub value)
 - Repair actions taken (when `--fix` is used)

3. **Summarize results:**

 - **If no drift found:** Report that local backlog and GitHub are in sync.
 - **If drift found (detect-only):** List the mismatches and suggest running `/yoke resync --fix` to repair them.
 - **If drift found and repaired (`--fix`):** Summarize what was fixed and note any items that could not be auto-repaired.

## Notes

- This command requires the `gh` CLI to be installed and authenticated.
- Detect-only mode makes zero GitHub API writes — safe to run at any time.
- The `--fix` mode updates GitHub issues to match local backlog state (local is source of truth).
- Frozen labels: if `items.frozen=1` in the DB but GitHub lacks the `frozen` label (or vice versa), resync detects and repairs the drift via `sync_frozen_label()`.
- Blocked labels: same shape as frozen, sourced from `items.blocked`. Repaired via `sync_blocked_label()`. Drift is reported as `HC-blocked-label-drift`. The legacy `status:blocked` label is removed automatically when the flag clears so a row repaired by the migration converges on a single indicator.
- Run `/yoke resync` periodically or after bulk backlog changes to catch drift early. This is part of Ouroboros — Yoke's self-improvement system.
