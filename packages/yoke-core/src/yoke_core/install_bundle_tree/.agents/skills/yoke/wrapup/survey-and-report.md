# Wrapup — Survey and Report

```sh
yoke sessions touch --mode wrapup
```

1. Read `git status --porcelain` in the relevant project checkout/claimed lane.
   Show modified/untracked paths. Ask whether to commit, stash, or continue
   anyway; help complete the chosen action before proceeding.
2. Read active lanes and recent item state:

   ```sh
   yoke items overview list --json
   ```

   Filter `result.rows` whose `worktrees` array is non-empty and status is
   outside `idea`, `done`, `cancelled`, `failed`, `stopped`. Each nested
   worktree is active by contract. Render the returned `public_ref`, title,
   status, `branch` and `lane_role` for each; never construct a public ref
   from an internal id. Warn about open lanes: verify/advance them or checkpoint
   their current state before ending. Retain live release-wait claims and use
   the owning skill's park/handoff rules.
3. Gather `git log --oneline -20` with timestamps to identify this session's
   commits, recent overview rows by `updated_at`, and actual conversation.
   Include a brief events volume/anomaly summary:

   ```sh
   yoke events count --since "4 hours ago"
   yoke events anomalies --since "4 hours ago"
   ```

4. Produce a proportional report:

   - What We Did: items/status transitions, PR creation/merge, changed scope.
   - What Went Wrong: only actual failures, root cause and prevention; say
     smooth when none occurred.
   - What Took Too Long: retries/rework, dead ends, waits or excess exploration;
     estimate effort/time and a concrete improvement.
   - What Worked Well: effective patterns/tools worth reusing.
   - Unfinished Business: objective, completed/remaining work, blockers,
     branch/lane/paths, next action and durable evidence links.

Continue with [record-and-close.md](record-and-close.md).
