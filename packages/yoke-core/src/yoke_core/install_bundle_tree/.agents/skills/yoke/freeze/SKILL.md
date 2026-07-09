---
name: freeze
description: "Freeze a backlog item — removes it from the active board without changing its status."
argument-hint: "YOK-N"
---

# /yoke freeze YOK-N

Freeze a backlog item. Freezing removes the item from the board's normal status-based sections and places it in the Freezer section, without changing its actual status. The item retains its real status (e.g., `implementing`, `planned`) and can be thawed later to return it to the board.

Use this when an item is blocked, deprioritized, or parked temporarily and you don't want it cluttering the active board.

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
 STATUS=$(yoke items get {N} status)
 FROZEN=$(yoke items get {N} frozen)
 ```

 If the query returns empty (item not in DB), stop with error:
 > Item YOK-{N} not found.

3. **Reject done items:** If `STATUS` is `done`, stop with error:
 > Cannot freeze a done item.

 Done items are complete and should not be frozen. If you need to reopen a done item, advance it back into the appropriate in-flight status first.

4. **Check if already frozen:** If `FROZEN` is `true`, stop with a note:
 > YOK-{N} is already frozen. Nothing to do.

5. **Acquire a work claim.** The `items.scalar.update` dispatch refuses
   to mutate an item unless the calling session already holds an active
   claim on it. Acquire one before the freeze mutation:

   ```bash
   yoke claims work acquire \
       --item "YOK-{N}" --reason freeze
   ```

   If the call exits non-zero because another session holds the claim,
   stop and have the operator coordinate with the holder — do not
   attempt to override.

6. **Set `frozen=true` via the canonical adapter.** The wrapped
   `items.scalar.update` adapter dispatches through the typed registry
   and rebuilds the board as a downstream side effect.

   ```bash
   yoke items scalar update YOK-{N} --field frozen --value true
   ```

   A non-zero exit code indicates the dispatcher refused the call (e.g.
   the item is already frozen, or the lifecycle gate refused). GitHub
   label-sync warnings surface as `warning: github_sync_degraded: ...`
   lines on stderr; the freeze itself still succeeded when exit code is
   0.

7. **Release the work claim.** Drop the claim now that the freeze
   mutation has applied so the item is not left stuck owned by this
   session:

   ```bash
   yoke claims work release \
       --item "YOK-{N}" --reason freeze-complete
   ```

8. **Commit the changes.**
   ```bash
   git diff --cached --quiet || git commit -m "YOK-{N}: freeze"
   ```

9. **Report:**
 > **YOK-{N}** ({title}): frozen
 >
 > The item retains its `{STATUS}` status but is now hidden from the active board.
 > To restore it: `/yoke thaw YOK-{N}`

## Notes

- Freezing does **not** change the item's `status`. The item keeps its real status (`implementing`, `planned`, etc.) and will return to the correct board section when thawed.
- You cannot freeze a `done` item. Done items are already complete and off the active board.
- The frozen item will appear in the **Freezer** section of `.yoke/BOARD.md` after the board rebuild.
