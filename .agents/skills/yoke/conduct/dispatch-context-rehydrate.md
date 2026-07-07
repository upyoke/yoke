# 5f-rehydrate. Prior Attempt Rehydration (shared sub-step)

Extracted from `dispatch-context.md`. Referenced from `dispatch-context-dispatch.md` before Engineer dispatch and from `engineer-tester-closeout.md` when a retry needs prior attempt context.

This sub-step assembles context from prior Engineer attempts and Tester rejections for injection into the Engineer dispatch prompt. It converts cross-session failures into learning by surfacing what was already tried.

**When to run:** Before every Engineer dispatch (first attempt and retries). On first attempts with no prior data, this step produces an empty block and no context is injected.

**Input:** `_id` (item numeric ID), `_type` (issue or epic), and for epics: `_epic_id`, `_task_id`.

### Step 1: Query prior progress notes

**For epic tasks:**
```bash
_prior_notes=$(python3 -m yoke_core.cli.db_router query "SELECT note_num, body, created_at FROM epic_progress_notes WHERE epic_id='${_epic_id}' AND task_num='${_task_id}' ORDER BY note_num ASC")
```

**For standalone issues:** Progress notes are not used for issues (no `epic_progress_notes` rows). Set `_prior_notes` to empty.

### Step 2: Query prior tester reviews

**For epic tasks:**
```bash
_prior_reviews=$(python3 -m yoke_core.cli.db_router query "SELECT CASE qr.verdict WHEN 'pass' THEN 'PASS' WHEN 'fail' THEN 'FAIL' ELSE 'FAIL' END, COALESCE(NULLIF(qr.raw_result, '')::jsonb #>> '{body}', ''), qr.created_at FROM qa_runs qr JOIN qa_requirements qreq ON qr.qa_requirement_id = qreq.id WHERE qreq.qa_kind = 'implementation_review' AND qreq.epic_id='${_epic_id}' AND qreq.task_num='${_task_id}' ORDER BY qr.created_at ASC")
```

**For standalone issues:**
```bash
_prior_reviews=$(python3 -m yoke_core.cli.db_router query "SELECT CASE qr.verdict WHEN 'pass' THEN 'PASS' WHEN 'fail' THEN 'FAIL' ELSE 'FAIL' END, COALESCE(NULLIF(qr.raw_result, '')::jsonb #>> '{body}', ''), qr.created_at FROM qa_runs qr JOIN qa_requirements qreq ON qr.qa_requirement_id = qreq.id WHERE qreq.qa_kind = 'implementation_review' AND qreq.item_id='${_id}' AND qreq.epic_id IS NULL ORDER BY qr.created_at ASC")
```

### Step 3: Assemble the rehydration block

If both `_prior_notes` and `_prior_reviews` are empty, set `_rehydration_block` to empty string and return. No context is injected for first-attempt dispatches with no prior history.

Otherwise, build the block:

```
## Prior Attempts

WARNING: Previous engineer sessions attempted this task and failed. Study the failures below carefully before starting. Do NOT repeat the same approaches that already failed.

{If _prior_notes is non-empty:}
### Progress Notes from Prior Attempts
{For each row in _prior_notes (pipe-separated: note_num|body|created_at):}
**Note {note_num}** ({created_at}):
{body}

{If _prior_reviews is non-empty:}
### Prior Tester Reviews
{For each row in _prior_reviews (pipe-separated: verdict|body|created_at):}
**Review ({verdict}, {created_at}):**
{body}
```

Store the assembled text as `_rehydration_block`.

### Step 4: Size guard

If `_rehydration_block` exceeds 3000 characters, truncate to the most recent 2 reviews and most recent 3 progress notes. Append a note:
```
(Prior attempt history truncated — {total_notes} notes, {total_reviews} reviews available in DB)
```

This prevents rehydration context from consuming the Engineer's context budget on items with long failure histories.
