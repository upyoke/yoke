# Merge — Conflict Handling

Operator-facing recovery procedures for when the retained merge watcher (`python3 -m yoke_core.tools.watch_merge merge-worktree`) reports conflicts (exit code 3) or fails hard (exit code 1). Also captures the general Notes that describe merge sequencing invariants.

---

## When merge reports conflicts (exit code 3)

When `python3 -m yoke_core.tools.watch_merge merge-worktree` exits with code 3, the underlying merge engine found conflicts that its deterministic auto-resolver could not handle, but the agent may be able to resolve using judgement. The wrapper preserves the engine's structured per-file conflict classification on stderr:

```
CONFLICT|path/to/file.sh|additive (auto)
CONFLICT|path/to/test.sh|overlapping (needs agent judgement)
```

Classifications:
- **generated (auto)** / **doc (auto)** / **yoke-gen (auto)** — script auto-resolves these
- **additive (auto)** — both sides only added lines (no deletions from base); script auto-resolves via union merge
- **doc (branch-modified, manual)** — doc file intentionally changed on the branch; review needed
- **overlapping (needs agent judgement)** — conflicting edits that are not provably additive; the agent should inspect and resolve

**Agent resolution flow (exit code 3):**

1. Parse the `CONFLICT|file|classification` lines from stderr to understand each conflict
2. `cd {worktree-path}` and `git merge origin/main` (or `git rebase origin/main`)
3. For each conflicting file, inspect the conflict markers and use judgement:
 - **Additive patterns** (both sides added independent content at the same point): keep both additions, choosing a sensible order
 - **Overlapping patterns** (both sides changed the same lines): understand the intent of each change and produce a correct merge
 - **Structural patterns** (imports, exports, registrations): merge both sides' additions
 - When uncertain, prefer the branch version for files the branch intentionally modified, and the main version for drift
4. `git add <resolved-files> && git commit` (or `git rebase --continue`)
5. Re-run `/yoke merge {epic-id}` — it will resume from the resolved state

**Safety boundary:** If you cannot confidently determine the correct resolution for a conflict, halt and report the conflict to the operator rather than guessing. The additive classification is a strong signal but not the only one — use your understanding of the codebase.

## When merge fails with hard conflicts (exit code 1)

If the merge fails with exit code 1 (test failure, push failure, CI failure, or other non-conflict errors), the merge script handles cleanup internally.

**Why this happens:** When multiple worktree branches modify related files, the first branch merges cleanly but changes main. The second branch then conflicts with the updated main. This is expected for multi-worktree epics — the sequential merge order keeps it to at most one conflict point.

**Resolution steps:**
1. Read the diagnostic output — it shows the exact error and worktree path
2. `cd {worktree-path}` (path is printed in the error)
3. `git rebase origin/main`
4. Resolve conflicts in the listed files
5. `git add <resolved-files> && git rebase --continue`
6. Re-run `/yoke merge {epic-id}` — it will skip already-merged branches and resume from the failed one

**If conflicts are complex**, dispatch an integration-fix task instead of resolving manually:
1. Create a task: `/yoke idea "Integration fix: {branch} rebase conflicts after {previous-branch} merge"`
2. Dispatch it to the existing worktree to let the Engineer resolve the conflicts

**Prevention tip:** Have the Architect assign shared files (router configs, index files) to a single worktree so cross-branch conflicts are rare.

## Notes

- Merges are **sequential** to avoid compounding conflicts. Each branch rebases onto the updated main after the previous branch was merged.
- Generated files (flagged by the Architect in the worktree plan) are auto-resolved. If the only conflicts are in generated files, the merge proceeds automatically.
- If tests fail after rebase, the merge script exits with status 1. This is treated as an integration failure, but future/planned item ownership or a planned path claim is not a waiver for the current merge failure. Do not use `path-claim-override` for a planned future claim when dependency or claim reconciliation can resolve the ordering; override is last resort for irreducible live collisions and requires explicit operator approval.
- The merge script uses `--force-with-lease` for pushing rebased branches (safe force push).
- CI timeout is 30 minutes. If CI doesn't complete in that time, the merge fails.
