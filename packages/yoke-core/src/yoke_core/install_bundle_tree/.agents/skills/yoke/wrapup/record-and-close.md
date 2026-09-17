# /yoke wrapup steps 5–10 — record learnings, continuity, and commit

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

6. **Offer to file work items:**

 For each problem or friction point in the "What Went Wrong" and "What Took Too Long" sections, ask the user:

 ```
 File a work item for this?
 - {problem summary}
 ```

 If the user approves, use `/yoke idea` to create the work item. The ouroboros entries from step 5 serve as the raw log; work items are the actionable follow-up.

 If there are no problems or friction points worth creating a work item for, skip this step.

7. **Update item continuity fields:**

 For any items that were worked on during this session, check if their structured fields / rendered item body reflect the current status and context. If not, update the authoritative structured field now — this is the primary continuity mechanism for future sessions.

 Full replacements go through the `items.structured_field.replace` function call. For in-flight execution context an issue lane needs after compaction or session swap, prefer the `Progress Log` section via `items.structured_field.section_upsert` (see AGENTS.md `## Progress Log`).

 ```json
 {
   "function": "items.structured_field.replace",
   "actor": {"session_id": "<this-session>"},
   "target": {"kind": "item", "public_ref": "PREFIX-{N}"},
   "intent": "wrapup_continuity",
   "payload": {
     "field": "spec",
     "content": "<full field body>"
   },
   "preconditions": {"allow_empty": false, "allow_shrinkage": false}
 }
 ```

 Allowed fields: `spec`, `design_spec`, `technical_plan`, `worktree_plan`, `shepherd_log` (epic-only), `shepherd_caveats` (epic-only), `test_results`, `deploy_log`.

8. **Record session continuity:**

The report is assembled for the current session; continuity is recorded in
the item Progress Log and Ouroboros field-notes rather than in a separate
report store.

For each item worked on during the session, append a current-state
checkpoint through the registered Progress Log writer:

```bash
yoke items progress-log append PREFIX-N \
  --headline "Session checkpoint" \
  --content "Objective: ...
Standing decisions/holds: ...
Active work: ...
Blockers: ...
Next action: ...
Evidence: ..." \
  --source wrapup
```

For observations that do not belong to an item, append a field-note with the
appropriate kind and concrete evidence:

```bash
yoke ouroboros field-note append --kind <failed|new|unclear|observation> \
  --evidence "..."
```

Hold the relevant work claim while writing item continuity and use the
registered commands so the next session can read the same authoritative
state.

9. **Display the session summary:**

 Print a concise summary to stdout from the report assembled in step 4:

 ```
 # Session Wrapup

 ## Accomplishments
 - {item}: {old-status} → {new-status}
 - ...

 ## Ouroboros Entries Logged
 - {count} entries ({N} problems, {N} friction, {N} ideas, ...)

 ## Work items Filed
 - PREFIX-{N}: {title}
 - (or: none)

 ## Unfinished Business
 - {summary of what's pending}
 - (or: none — clean session)

 Report emitted in session output; continuity recorded in item Progress Log and Ouroboros field-notes.
 ```

10. **Commit wrapup artifacts:**

 ```bash
 # The report is prompt output; no generated report file needs to be committed.
 # Commit any other wrapup artifacts (e.g., ouroboros entries, patterns updates).
 git diff --cached --quiet || git commit -m "wrapup: session summary and ouroboros entries"
 ```

## Notes

- This command is entirely prompt-driven — no shell scripts needed. You (the session agent) review your own conversation history and synthesize the report.
- Speed matters — the user is ending a session, not starting a project. Aim for 2-3 minutes, not 10.
- The ouroboros entries are raw observations. `/yoke curate` handles clustering, work item promotion, and archiving later.
- Do not attempt to curate during wrapup — just log raw and move on.
- If the session was trivial (e.g., single small fix, no problems), keep the wrapup proportionally brief. A one-item session doesn't need a 5-section report.
- The "What Went Wrong" section should include root causes, not just symptoms. "Tests failed" is not useful. "Tests failed because the mock gh wasn't on PATH in the test harness" is useful.
- Unfinished business is the current-state checkpoint: paths, branch, next action, blockers, links to evidence — not a restated session transcript.
