# /yoke blitz steps 4–5 — integration map and slice execution

## 4. Build an integration map

The preparation call ensures the default worker lane through the active
authority, materializes every registered active lane on this machine, and
records each exact local path back through the guarded function-call surface.
Keep execution sequential in the default lane unless additional worker lanes
and an explicit integration lane have been registered through the universal
item-worktree surface:

```text
yoke item-worktrees create ITEM --lane-role worker --branch BRANCH
```

Repeat the same registered call with `--lane-role integration` for the one
explicit integration lane, then rerun the ordinary worktree preparation to
materialize every pathless registration over either HTTPS or machine-local
Postgres. Verify the authoritative set and its recorded paths with:

```text
yoke item-worktrees list ITEM --json
```

The item owns every registered lane; the main session holds the item work claim
while coordinating integration. Never parallelize by inventing an unregistered
branch or directory. Every worker brief must name:

- its outcome and exact file responsibility;
- its registered worktree;
- the focused verification it must run;
- the Slice Log entry it must append;
- the commit and integration expectation;
- that other workers exist and their edits must not be reverted.

The main session continues independent integration work while workers run.
It does not delegate the final plan reconciliation or full verification.

## 5. Execute and integrate one slice at a time

For each slice:

1. Re-read the relevant current document section and live coordination
   entries.
2. Make the smallest coherent change in its registered worktree.
3. Run focused verification with capture-first output — the individual
   failing tests, the changed module's paths, or the project's impacted
   selection (`yoke watch pytest --impacted main --bounded` here, which
   reports an unbounded selection instead of widening; for a project
   declaring `ci_workflow_file` it runs on that CI against the pushed
   lane commit, so commit and let CI run it; `--local` is only a small
   targeted check expected to finish in about one minute). When a slice has an
   attached Command case, that case run is the slice's one full execution:
   do not run the project's full sweep by hand and then hand the same tree to
   `yoke qa case run`, which re-runs the identical registered command. It
   streams live to stderr and names its raw capture file before starting.
4. Commit the slice with a descriptive current-function message.
5. Resolve the exact changed files and re-survey immediately before merge:

   ```text
   yoke direct-workflow blitz survey ITEM --path <actual-file> [--path <actual-file> ...] --json
   ```

6. Read each survey advisory and choose proceed or yield. Independent edits
   resolve at merge; order-dependent work authors a dependency, drops the
   claim, and re-offers. A planned claim is not a stronger reason to yield
   than an active one. Coordinate through `Slice Log`, reorder work, or
   register complete path claims before the next prepare. Do not silently
   resolve another owner's semantic changes.
7. When an integration lane is registered, it is the only merge source.
   Fold completed worker commits into it with `git merge` from inside the
   integration worktree; worker lanes keep building but never land on their
   own. Once the integration pull request is queued, do not commit or merge
   into that branch until it lands — a push removes it from the queue. Workers
   may continue in their own lanes during the wait; fold that work only after
   main fast-forwards from the completed landing.

   Merge the integrated slice through the standalone-item merge boundary.
   `--skip-status` keeps the item non-terminal — a Blitz closes out only when
   its execution document completes:

   ```text
   yoke watch merge --print-streaming-pair merge-item -- ITEM --skip-status --wait --json
   ```

   Run the printed command; that run is the merge. Only a verified
   `background-wake` route may release to its one subscription; the `in-turn`
   command blocks until the landing finishes and expects no later completion
   notice. Continue only once the response carries `merge_sha`. A
   queue-declared project keeps all registered lanes until the item is done.
   Only a project using the local merge engine needs to re-prepare the lane
   before the next slice, because that engine's cleanup deletes the landed
   branch. Run the delivery or migration action a slice itself requires; do
   not add one after every landing.
8. Append a cold-start-readable checkpoint:

   ```text
   yoke strategy coordination append <SLUG> --section "Slice Log" \
     --entry "<slice, merge SHA, verification, delivery, changed plan facts, next boundary>" \
     --project <PROJECT>
   ```

9. As the item-claim holder, revise the authoritative plan when the result
   changes scope, sequencing, decisions, or completion state. Use the
   registered strategy write surface and the current optimistic-concurrency
   token. An append is not a substitute for updating stale plan content.

Keep slices small and frequent. Do not hold completed code on a long-lived
branch merely to produce one terminal merge.


Next: [`review-and-complete.md`](review-and-complete.md).
