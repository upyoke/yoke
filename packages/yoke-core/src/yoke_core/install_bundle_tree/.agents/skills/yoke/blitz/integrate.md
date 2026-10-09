# Blitz — map and integrate slices

## 4. Integration map

Preparation ensures the default worker lane, materializes all registered active
lanes and records exact local paths through the guarded authority. Execute
sequentially there unless extra workers and one integration lane are registered:

```sh
yoke item-worktrees create ITEM --lane-role worker --branch BRANCH
yoke item-worktrees list ITEM --json
```

Repeat create with `--lane-role integration`, then rerun the ordinary worktree preparation
to materialize pathless registrations over either HTTPS or machine-local
Postgres. Verify every registered worker worktree and its recorded path. The item owns every lane; main holds
its work claim. Parallel work requires registered branches/directories.

Each worker brief names outcome/exact files, registered lane, focused checks,
Slice Log entry, commit/integration expectation, and other workers whose edits
must be preserved. Main continues independent work and retains final
reconciliation/full verification.

## 5. Execute one coherent slice

1. Re-read its current document section and live coordination entries.
2. Make the smallest coherent change in the registered lane.
3. Capture focused checks: failing tests, changed modules or
   `yoke watch pytest --impacted main --bounded`. An unbounded selection stops
   rather than widening. With `ci_workflow_file`, commit first and let the
   wrapper run CI against the pushed lane commit. `--local` is only a small
   targeted check expected within about one minute.
   An attached Command case is the slice's one full execution via
   `yoke qa case run`; avoid a duplicate full sweep. It streams stderr and
   names the raw capture before starting.
4. Commit with a current-function description.
5. Resolve exact changed files and re-survey immediately before merge:

   ```sh
   yoke direct-workflow blitz survey ITEM --path <actual-file> [--path <actual-file> ...] --json
   ```

6. Judge each advisory: independent edits resolve at merge; ordered edits
   require dependency/drop claim/re-offer. Planned claims are no stronger.
   Coordinate in Slice Log, reorder or register complete claims before prepare;
   preserve other owners' semantic changes.
7. A registered integration lane is the only merge source: `git merge`
   completed worker commits inside it. Queued integration branches accept no
   commits/merges until landing; pushing removes them from the queue. Workers
   may continue in their lanes; fold work only after main fast-forwards from
   the completed landing.

   Merge through the standalone-item boundary. `--skip-status` retains the
   non-terminal item until document completion:

   ```sh
   yoke watch merge --print-streaming-pair merge-item -- ITEM --skip-status --wait --json
   ```

   Run the printed command; printing does not merge. A verified
   `background-wake` route may release to its single subscription;
   `in-turn` blocks through landing with no later completion notice.
   Continue only with `merge_sha`. Queue projects retain all lanes until done.
   Only local merge-engine cleanup deletes a landed branch and requires
   re-preparation before the next slice. Perform delivery/migration actions
   required by that slice, without adding one to every landing.
8. Append a cold-start checkpoint:

   ```sh
   yoke strategy coordination append <SLUG> --section "Slice Log" \
     --entry "<slice, merge SHA, verification, delivery, changed plan facts, next boundary>" \
     --project <PROJECT>
   ```

9. As claim holder, revise authoritative scope/order/decisions/completion with
   the registered strategy write and current optimistic-concurrency token.
   Append-only logs do not repair stale plan content.

Integrate small completed slices frequently, rather than holding them for
a single terminal merge. Next: [review-and-complete.md](review-and-complete.md).
