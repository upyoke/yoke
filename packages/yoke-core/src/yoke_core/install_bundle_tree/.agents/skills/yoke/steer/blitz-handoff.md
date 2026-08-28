# Blitz handoff

Steer existing work in its pinned workflow; never convert or re-file it.
For ordinary new work filed by the steerer, default to
`/yoke idea --workflow dash` unless the work genuinely needs Issue, Epic, or
Blitz structure, or the operator directs another workflow.

When a chunk of the document needs an implementer:

1. File a Blitz from the document (`/yoke idea --workflow blitz "{title}"`).
   Link it before anyone claims it:

   ```text
   yoke strategy execution link ITEM --slug {SLUG} --project {_project}
   ```

2. **Release the document lock** so the worker can claim the Blitz. A
   session-held lock and a live Blitz on the same slug are mutually exclusive;
   leaving the lock held is a handoff defect.

   ```text
   yoke strategy doc-claim release {SLUG} --project {_project} --reason "blitz-handoff"
   ```

3. Encode `item_dependencies` edges, or an explicit no-edges attestation on
   the filed items, in the same action that files a related batch. Title-only
   batches that are already claimable are a defect.

4. Launch per [`worker-lifecycle.md`](worker-lifecycle.md). A successful Blitz
   `done` transition archives its linked execution document automatically and
   releases the item-owned document claim. Do not archive it by hand and do
   not re-acquire a lock on that archived document. Continued steering uses
   the parent or another active strategy document through the normal claim
   flow.
