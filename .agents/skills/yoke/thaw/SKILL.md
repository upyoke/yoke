---
name: thaw
description: "Thaw a frozen backlog item — return it to the active board in its normal status section."
argument-hint: "YOK-N"
---

# /yoke thaw YOK-N

Thaw a frozen backlog item. Thawing sets `frozen=false` and returns the item to its normal status-based section on the board.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug not worth a ticket, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Arguments

- `YOK-N` — Backlog item ID. Accepts prefixed IDs, zero-padded prefixed IDs, or bare numeric IDs.

## Steps

1. **Parse the ID:** Extract the numeric part from the argument (strip `YOK-` prefix if present, strip leading zeros). Zero-pad to 3 digits for the filename (`{NNN}`).

2. **Read the backlog item from the DB:**
 ```bash
 FROZEN=$(yoke items get {N} frozen)
 ```

 If the query returns empty (item not in DB), stop with error:
 > Item YOK-{N} not found.

3. **Check if actually frozen:** If `FROZEN` is not `true`, stop with a note:
 > YOK-{N} is not frozen. Nothing to do.

4. **Acquire a work claim.** The `items.scalar.update` dispatch refuses
   to mutate an item unless the calling session already holds an active
   claim on it. Acquire one before the thaw mutation:

   ```bash
   yoke claims work acquire \
       --item "YOK-{N}" --reason thaw
   ```

   If the call exits non-zero because another session holds the claim,
   stop and have the operator coordinate with the holder — do not
   attempt to override.

5. **Set `frozen=false` via the canonical adapter.** The wrapped
   `items.scalar.update` adapter dispatches through the typed registry,
   removes the GitHub `frozen` label best-effort, and rebuilds the board
   as a downstream side effect.

   ```bash
   yoke items scalar update YOK-{N} --field frozen --value false
   ```

   Label-sync warnings surface as `warning: github_sync_degraded: ...`
   lines on stderr; the thaw itself still succeeded when exit code is 0.

6. **Release the work claim.** Drop the claim now that the thaw
   mutation has applied so the item is not left stuck owned by this
   session:

   ```bash
   yoke claims work release \
       --item "YOK-{N}" --reason thaw-complete
   ```

7. **Commit the changes.**
   ```bash
   git diff --cached --quiet || git commit -m "YOK-{N}: thaw"
   ```

8. **Report:**
 > **YOK-{N}** ({title}): thawed
 >
 > The item is back on the board in the `{status}` section.

## Notes

- Thawing does **not** change the item's `status`. The item returns to whichever board section matches its current status.
- If the item is not frozen (`frozen: false` or not set), the command is a no-op.
