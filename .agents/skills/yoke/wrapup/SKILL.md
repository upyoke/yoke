---
name: wrapup
description: "Structured session wrap-up: ouroboros reflections, unfinished business, session summary."
argument-hint: "(no arguments)"
---

# /yoke wrapup

Structured end-of-session wrap-up. Reviews the session's work, logs ouroboros reflections, captures unfinished business, and offers to file tickets for discovered issues.

This is the bookend to session-start — if we enforce how sessions begin, we enforce how they end.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug not worth a ticket, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Philosophy

**Events table summary.** During the session review, query the events table for this session's telemetry: `yoke events count --since "4 hours ago"` for volume and `yoke events anomalies --since "4 hours ago"` for failure patterns. Include a brief events summary in the wrapup report.

**Be the giant.** We stand on inherited shoulders; leave a leg up for the next agent by making this artifact cold-start complete. The wrapup report is the cold-start context for whoever picks up this work next. Include specific decisions made, dead ends explored, and the "why" behind non-obvious choices. Leave context your future self will need.

## Steps

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
 python3 -m yoke_core.cli.db_router query "SELECT id, title, worktree, status FROM items WHERE status NOT IN ('idea','done','cancelled','failed','stopped') AND worktree IS NOT NULL AND worktree <> '';"
 ```

 If any items are still active with worktrees, warn:

 ```
 ⚠ In-flight worktrees still open:
 - YOK-{N}: {title} ({status}, branch: {worktree})

 These have uncommitted work on separate branches. Consider advancing them to done or documenting their state in the appropriate structured item fields before ending the session.
 ```

3. **Gather session context:**

 Collect the raw material for the wrapup report:

 a. **Recent commits this session:** Run `git log --oneline -20` and identify commits from this session (use timestamps — commits from the last few hours).

 b. **Items touched:** Query items whose `updated_at` timestamp is recent:
 ```bash
 python3 -m yoke_core.cli.db_router query -separator '|' "SELECT id, title, status FROM items WHERE updated_at >= to_char((now() AT TIME ZONE 'UTC') - interval '4 hours', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') ORDER BY updated_at DESC;"
 ```

4. **Generate the wrapup report:**

 Review the full conversation history for this session. Synthesize the following sections:

 ### What We Did
 - List each item worked on with its status transition (e.g., "YOK-N: implementing -> reviewed-implementation")
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

5. **Write ouroboros log entries:**

For each distinct observation from the wrapup report (problems, friction points, ideas, cross-critiques), insert a structured entry through the registered Ouroboros entry writer.

 Pipe the observation body directly to `yoke ouroboros entry insert --stdin`:

```bash
cat << 'ENTRY_EOF' | yoke ouroboros entry insert --stdin \
 --timestamp "{current UTC ISO 8601}" \
 --agent "conduct" \
 --context "wrapup" \
 --category "{category}"
 {observation body — 1-3 sentences, concrete and actionable}
 ENTRY_EOF
 ```

 Repeat for each distinct observation. The body must be piped via stdin (never passed as a positional argument) to avoid shell quoting issues with backticks, dollar signs, and quotes in the observation text.

 **Category guidelines:**
 - `problem` — something broke or failed
 - `friction` — something worked but was harder than it should be
 - `idea` — a concrete improvement suggestion
 - `cross-critique` — feedback on another agent's or tool's behavior
 - `metric` — quantitative data point (timing, counts, rates)
 - `pattern` — a recurring observation confirmed across multiple instances

 Write one entry per distinct observation. Do not combine unrelated observations into a single entry.

6. **Offer to file tickets:**

 For each problem or friction point in the "What Went Wrong" and "What Took Too Long" sections, ask the user:

 ```
 File a ticket for this?
 - {problem summary}
 ```

 If the user approves, use `/yoke idea` to create the ticket. The ouroboros entries from step 5 serve as the raw log; tickets are the actionable follow-up.

 If there are no problems or friction points worth ticketing, skip this step.

7. **Update item continuity fields:**

 For any items that were worked on during this session, check if their structured fields / rendered item body reflect the current status and context. If not, update the authoritative structured field now — this is the primary continuity mechanism for future sessions.

 Full replacements go through the `items.structured_field.replace` function call. For in-flight execution context an issue lane needs after compaction or session swap, prefer the `Progress Log` section via `items.structured_field.section_upsert` (see AGENTS.md `## Progress Log`).

 ```json
 {
   "function": "items.structured_field.replace",
   "actor": {"session_id": "<this-session>"},
   "target": {"kind": "item", "item_id": {N}},
   "intent": "wrapup_continuity",
   "payload": {
     "field": "spec",
     "content": "<full field body>"
   },
   "preconditions": {"allow_empty": false, "allow_shrinkage": false}
 }
 ```

 Allowed fields: `spec`, `design_spec`, `technical_plan`, `worktree_plan`, `shepherd_log` (epic-only), `shepherd_caveats` (epic-only), `test_results`, `deploy_log`.

8. **Save the wrapup report to DB and generate view:**

 Persist the full wrapup report (all 5 sections from step 4, plus the summary from below) to the DB, then render the `.md` view file.

 First, compose the full report body with this structure:

 ```markdown
 # Session Wrapup — {YYYY-MM-DD}

 ## What We Did
 {content from step 4}

 ## What Went Wrong
 {content from step 4}

 ## What Took Too Long
 {content from step 4}

 ## What Worked Well
 {content from step 4}

 ## Unfinished Business
 {content from step 4}

 ## Summary
 - Items: {list of YOK-N transitions}
 - Ouroboros entries: {count}
 - Tickets filed: {list or "none"}
 ```

 Then save to DB and generate the `.md` view. Use a session timestamp in `{YYYY-MM-DD}-{HHmm}` format (current UTC time):

 ```bash
 SESSION_TS="{YYYY-MM-DD}-{HHmm}"
 cat << 'WRAPUP_EOF' | python3 -m yoke_core.cli.db_router ouroboros insert-wrapup "$SESSION_TS"
 {full wrapup report body from above}
 WRAPUP_EOF
 python3 -m yoke_core.cli.db_router ouroboros generate-wrapup "$SESSION_TS"
 ```

 The `generate-wrapup` command renders the report to `ouroboros/wrapups/{SESSION_TS}.md`. This file is a local generated view (gitignored since) — the DB `wrapup_reports` table is the canonical source. The local `.md` file survives context clears and can be reviewed by future sessions or `/yoke curate`.

9. **Display the session summary:**

 Print a concise summary to stdout (same content as the Summary section saved in step 8):

 ```
 # Session Wrapup

 ## Accomplishments
 - {item}: {old-status} → {new-status}
 - ...

 ## Ouroboros Entries Logged
 - {count} entries ({N} problems, {N} friction, {N} ideas, ...)

 ## Tickets Filed
 - YOK-{N}: {title}
 - (or: none)

 ## Unfinished Business
 - {summary of what's pending}
 - (or: none — clean session)

 Report saved to: ouroboros/wrapups/{filename}
 ```

10. **Commit wrapup artifacts:**

 ```bash
 # ouroboros/wrapups/ is gitignored — no git add needed.
 # Commit any other wrapup artifacts (e.g., ouroboros entries, patterns updates).
 git diff --cached --quiet || git commit -m "wrapup: session summary and ouroboros entries"
 ```

## Notes

- This command is entirely prompt-driven — no shell scripts needed. You (the session agent) review your own conversation history and synthesize the report.
- Speed matters — the user is ending a session, not starting a project. Aim for 2-3 minutes, not 10.
- The ouroboros entries are raw observations. `/yoke curate` handles clustering, ticket promotion, and archiving later.
- Do not attempt to curate during wrapup — just log raw and move on.
- If the session was trivial (e.g., single small fix, no problems), keep the wrapup proportionally brief. A one-item session doesn't need a 5-section report.
- The "What Went Wrong" section should include root causes, not just symptoms. "Tests failed" is not useful. "Tests failed because the mock gh wasn't on PATH in the test harness" is useful.
- The unfinished business section should contain enough context for a cold-start session to pick up immediately — file paths, branch names, what's done, what remains, what's blocking.
