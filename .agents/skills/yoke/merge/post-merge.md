# Merge — Post-Merge Bookkeeping

Covers merge Step 7: after every branch has been merged, sync local main with origin, then close the epic GitHub issue, advance the linked backlog item to `done`, and record `merged_at`.

**Context variables** (set by earlier phases): `{epic-id}`, `_merge_stashed`.

---

7. **After all branches merged — sync local main with origin:**

 **CRITICAL: Pull the PR merge commits into local main BEFORE any bookkeeping.**
The retained merge watcher (`python3 -m yoke_core.tools.watch_merge merge-worktree`) attempts this internally, but failures are non-fatal. This explicit pull
 is the belt-and-suspenders guarantee that local main has all the merged code.

 ```bash
 # Stash dirty files if any (session artifacts, board rebuilds, etc.)
 _merge_stashed=0
 if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
 git stash push --include-untracked -m "yoke-pre-merge-sync"
 _merge_stashed=1
 fi

 # Pull all PR merge commits into local main
 git pull --rebase origin main

 # Restore stashed files
 if [ "$_merge_stashed" -eq 1 ]; then
 git stash pop
 fi
 ```

 If the pull fails, **STOP and report the error** — do not proceed with bookkeeping commits
 that would further diverge local from origin.

 Then proceed with bookkeeping:
 - Close the epic GitHub issue
 - **Ensure linked backlog item is `done` and set `merged_at`** (if applicable):
 Query the DB for the epic backlog item by its numeric `id` (`{epic-id}` IS the epic item's `items.id`):
 ```bash
 yoke db read --format lines "SELECT id, status FROM items WHERE id={epic-id} AND type='epic';"
 ```
 If found:
 1. Read the backlog item's current `status` field via the `items.get` function.
 2. If status is NOT `done`, advance it via `lifecycle.transition`. The post-merge bookkeeping path carries `payload.bypass_reason="merge:post-PR-done"` so the handler unblocks the merge-bookkeeping fast path (epics may still be in `reviewed-implementation`, `polishing-implementation`, `implemented`, or `release` while merge bookkeeping catches up). The same call closes the GitHub issue as a downstream side effect when `options.sync_github_body=true`.

    ```json
    {
      "function": "lifecycle.transition",
      "actor": {"session_id": "<this-session>"},
      "target": {"kind": "item", "item_id": {N}},
      "intent": "merge_post_pr_done",
      "payload": {"to": "done", "bypass_reason": "merge:post-PR-done"},
      "options": {"sync_github_body": true, "close_github_issue": true}
    }
    ```

 3. Set the merge timestamp by calling `items.scalar.update` with `payload.field="merged_at"`, `payload.value="{ISO timestamp}"`.
 - Report success with links to all merged PRs.
