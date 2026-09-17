# /yoke wrapup steps 1–4 — survey the session and generate the report

Stamp the session mode so the board's active-session row reflects the live phase (default `wait` misrepresents an active wrapup). Use the registered session wrapper:

```bash
yoke sessions touch \
 --mode wrapup
```

1. **Check for uncommitted work:**

 Run `git status --porcelain` in the project root. If there are uncommitted changes, warn:

 ```
 ⚠ Uncommitted changes detected:
 {list of modified/untracked files}

 Commit or stash these before wrapping up — uncommitted work is invisible to future sessions.
 ```

 Ask the user whether to commit now, stash, or continue anyway. If they choose to commit, help them commit before proceeding.

2. **Check for in-flight worktrees:**

 ```bash
 yoke items overview list --json
 ```

 Read `result.rows`. Keep rows whose `worktrees` array is non-empty and
 whose `status` is not `idea`, `done`, `cancelled`, `failed`, or `stopped`.
 Each nested worktree is active by contract. Render one line per nested
 worktree using the row's `public_ref`, `title`, and `status`, plus the
 worktree's `branch` and `lane_role`. Use `public_ref` exactly as returned;
 never synthesize a project-local reference from the global item id.

 If any items are still active with worktrees, warn:

 ```
 ⚠ In-flight worktrees still open:
 - {public_ref}: {title} ({status}, branch: {branch}, lane: {lane_role})

 These items still own active worktree lanes. Verify and advance them, or document their state in the appropriate structured item fields before ending the session.
 ```

3. **Gather session context:**

 Collect the raw material for the wrapup report:

 a. **Recent commits this session:** Run `git log --oneline -20` and identify commits from this session (use timestamps — commits from the last few hours).

 b. **Items touched:** Query items whose `updated_at` timestamp is recent:
 ```bash
 yoke db read --format lines "SELECT id, title, status FROM items WHERE updated_at >= to_char((now() AT TIME ZONE 'UTC') - interval '4 hours', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') ORDER BY updated_at DESC;"
 ```

4. **Generate the wrapup report:**

 Review the full conversation history for this session. Synthesize the following sections:

 ### What We Did
 - List each item worked on with its status transition (e.g., "PREFIX-N: implementing -> reviewed-implementation")
 - Note any PRs created or merged
 - Summarize the scope of changes (files touched, lines changed)

 ### What Went Wrong
 For each problem encountered during the session:
 - **What happened** — concrete description of the failure
 - **Root cause** — why it happened (not just the symptom)
 - **Prevention** — how to avoid it next time

 Only include problems that actually occurred. If the session was smooth, say so.

 ### What Took Too Long
 Identify steps that consumed disproportionate time or tokens:
 - Repeated retries or rework
 - Dead-end investigations
 - Waiting on slow operations
 - Unnecessary exploration

 For each, note the approximate time/effort and what could reduce it.

 ### What Worked Well
 Identify patterns, tools, or approaches that were particularly effective. These are candidates for reuse.

 ### Unfinished Business
 For each piece of incomplete work:
 - What was started but not finished
 - Current state (what's done, what remains)
 - Blocking issues (if any)
 - Where to find the work (branch, worktree, file paths)

 This section is critical for session continuity — the next session should be able to pick up seamlessly.


Next: [`record-and-close.md`](record-and-close.md).
