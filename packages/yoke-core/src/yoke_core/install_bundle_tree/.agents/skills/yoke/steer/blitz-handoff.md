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

2. Encode `item_dependencies` edges, or an explicit no-edges attestation on
   the filed items, in the same action that files a related batch. Title-only
   batches that are already claimable are a defect.

3. Choose the parent or another active strategy document for continued
   steering. The seat cannot stay live without a paired document, and the
   Blitz document must become available to its worker.

4. **Release the paired steering claim** so the worker can claim the Blitz.
   This atomically releases the document lock; direct document release is
   refused while the seat is active.

   ```text
   yoke claims steering release {CLAIM_ID} --reason "blitz-handoff"
   ```

5. When steering continues, immediately acquire a new pair and retain its new
   claim id. If no successor document exists, this is a terminal steering
   handoff; launch the worker, then stop the loop.

   ```text
   yoke claims steering acquire --project {_project} --doc {NEXT_SLUG} --reason "steer {NEXT_SLUG}"
   ```

   The gap between release and re-acquire strands nothing: workers address
   the steering role rather than this session, so anything sent while the
   scope was unowned parks and arrives in the re-acquire's handoff digest.
   Read that digest before resuming the loop.

6. Launch per [`worker-lifecycle.md`](worker-lifecycle.md). A successful Blitz
   `done` transition archives its linked execution document automatically and
   releases the item-owned document claim. Do not archive it by hand and do
   not re-acquire a lock on that archived document. Continued steering uses
   the parent or another active strategy document through the normal claim
   flow.
