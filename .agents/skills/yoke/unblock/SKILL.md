---
name: unblock
description: "Clear an item's blocked flag and return it to active dispatch."
argument-hint: "YOK-N"
---

# /yoke unblock YOK-N

Clear a backlog item's blocked flag. Unblocking sets `items.blocked = 0`
and clears `items.blocked_reason`, returning the item to its normal
board section (its preserved lifecycle `status` did not change while the
flag was set, so no status mutation is required to resume).

This is the operator counterpart to `/yoke block`. Item-level blocking
is a flag-driven primitive; it is unrelated to
`path_claims.state='blocked'`, which has its own activation flow.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug not worth a ticket, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Arguments

- `YOK-N` — Backlog item ID. Accepts prefixed IDs, zero-padded prefixed IDs, or bare numeric IDs.

## Steps

1. **Parse the ID.** Strip `YOK-` prefix if present, strip leading
   zeros.

2. **Read the backlog item.**
   ```bash
   BLOCKED=$(yoke items get {N} blocked)
   ```
   If the query returns empty (item not in DB), stop with error:
   > Item YOK-{N} not found.

3. **Check if actually blocked.** If `BLOCKED` is not `true`, stop with
   a note:
   > YOK-{N} is not blocked. Nothing to do.

4. **Clear the flag and the reason via the canonical adapter.** Use the
   wrapped `items.scalar.update` adapter once to clear the flag and once
   to clear the reason. The shared mutation path removes the GitHub
   `blocked` label best-effort and rebuilds the board.

   ```bash
   yoke items scalar update YOK-{N} --field blocked --value false
   yoke items scalar update YOK-{N} --field blocked_reason --null
   ```

   GitHub label-sync warnings surface as `warning: github_sync_degraded`
   lines on stderr; the unblock itself still succeeded when exit code is
   0. If the second write fails after the first succeeds, rerun the
   `blocked_reason --null` command after addressing the reported error.

5. **Commit.**
   ```bash
   git diff --cached --quiet || git commit -m "YOK-{N}: unblock"
   ```

6. **Report.**
   > **YOK-{N}** ({title}): unblocked
   >
   > The item is back on the board in the `{status}` section.

## Notes

- Unblocking does **not** change the item's lifecycle `status`. The
  item returns to whichever section its preserved status dictates.
- If the item is not blocked (`blocked=0` or unset), the command is a
  no-op.
- Path-claim hooks do **not** auto-release on item-level unblock —
  path-claim coordination state is independent of the item-level flag
  by design. If you need to also release a coordination claim
  use the path-claim CLI surface.
- This skill never auto-derives blocked state from anywhere; the
  operator is the source of truth. Item-level auto-unblock does not
  exist — only this skill flips the flag back to `false`.
