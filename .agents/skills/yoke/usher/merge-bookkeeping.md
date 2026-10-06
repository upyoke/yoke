# Usher — record generated task landing

Run after every registered task lane has a successful merge receipt.
The merge engine owns checkout synchronization and task receipts; do not
invent a parent landing while a branch is still pending or failed.

1. Verify the merged PR identities and target revision from those receipts.
   Resolve the project's declared default branch and verify local ancestry;
   if synchronization failed, report `merge_target_sync_failed` with the
   failing checkout and recovery before further bookkeeping. Preserve dirty
   state rather than rebasing or stashing another session's checkout.
2. Record the parent's verified `merged_at` through `items.scalar.update`.
   Retain every lane's PR and commit identity in the item's evidence.
3. Read the live pin and its exact immutable definition:

   ```bash
   yoke workflows item get "$_epic_ref" --json
   yoke workflows version get "<workflow_id>" "<workflow_version>" --json
   ```

4. Find the binding whose half-open interval contains the live stage. If
   already at the definition’s delivery wait, return to deployment now.
   Otherwise walk declared forward transitions one at a time, within usher’s
   bound interval, stopping on entry to the delivery wait. Use the actual source and target stage ids from the definition:

   ```json
   {
     "function": "lifecycle.transition.execute",
     "actor": {"session_id": "<this-session>"},
     "target": {"kind": "item", "public_ref": "PREFIX-N"},
     "intent": "usher_merge_bookkeeping",
     "payload": {
       "source_status": "<live stage>",
       "target_status": "<declared next stage>"
     }
   }
   ```

   Re-read the live stage after each transition. Never skip a stage, bypass
   a gate, force terminal success, or close the parent issue before terminal
   success. If no unique forward transition exists, halt with
   `merge_bookkeeping_transition_unresolved`, naming the pin and live stage;
   correct the workflow or obtain the operator's choice before continuing.
5. At the definition's delivery wait, return to [deploy.md](deploy.md).
   A successful merge is not successful delivery. `--merge-only` records the
   wait and retains the parent work claim; deployment stays with its caller.
   A refused gate is a blocker: preserve the current stage, record the named
   reason and recovery, and stop. Resume at that stage rather than replaying
   the lane merges.
6. After delivery, the pinned terminal transition and its gates own issue
   close-out. Report success only after reading terminal success; otherwise
   report the landed PRs and the remaining bound stage.
