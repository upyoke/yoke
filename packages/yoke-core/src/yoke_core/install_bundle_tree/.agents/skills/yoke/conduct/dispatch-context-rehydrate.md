# Conduct — prior attempt evidence

Before every Engineer dispatch, load prior task progress notes and reviews in
chronological order. Empty history omits the block. Preserve complete parent
public ref and local task number; never substitute numeric public tail for id.

Diagnostic reads use selected control-plane authority:

```text
yoke db read --format lines "SELECT note_num, body, created_at FROM epic_progress_notes WHERE epic_id=(SELECT item_id FROM item_refs WHERE public_ref='PREFIX-N') AND task_num={task_num} ORDER BY note_num ASC"
yoke workflow-item epic-task review-list --epic PREFIX-N --task-num {task_num}
```

Standalone items have no epic_progress_notes. Read their implementation-review
requirements/runs through registered QA lists, with item identity and no epic
scope. Task reviews use exact task identity. Do not reinterpret missing/failed
reads as evidence of no history or write a read value back to body.

Build ## Prior Attempts containing note number/date/body and review verdict/
date/body. Explain previous outcomes as systemic evidence: study already tried
approaches and pending feedback before work; no agent-error blame. Retain the
block only for this task, then clear on chain advance.

If >3000 characters, include latest3 notes and latest2 reviews, count withheld
rows and name the exact complete history read. Never cut an arbitrary body
midline or silently discard prior failures. Store _rehydration_block for prompt
assembly; no history means empty, not an empty heading placeholder.
