# Conduct — reflections, artifacts and QA

Read raw/progress capture paths printed by the wrapper. Helpers mint them
under the session scratch root; never guess OS-temp watcher paths. --raw-capture
is the operator's explicit pin. A yielded watcher continues through its owning
handle to exit; capture observation is not command completion.

## Reflections

Use the installed harness manifest and capture receipts. Claude's PostToolUse
Agent hook (`yoke_core.domain.reflection_capture_hook`) normally captures the
complete delimited response once; no duplicate
manual insert. Codex custom-agent returns do not fire that Agent matcher; the
retained operator/debug parity owner consumes the captured response with actual
project and canonical role before continuing:

```text
python3 -m yoke_core.domain.reflection_capture --default-agent {ROLE} --project {PROJECT} --output-text {RESPONSE_TEXT}
```

For large output use its documented stdin form. No silent project=yoke fallback.
Recovery/backfill requires evidence automatic capture was absent; preserve
ReflectionCaptureHookFired/Unhandled diagnostics. Reflection failures report a
field-note, not a fabricated capture. Keep full response only until captured.

## Tester artifacts and anticipated coverage

Inspect actual lane dirt after return. Commit only verified review artifacts
the Tester produced; reviews/reflections normally live in DB, not filesystem.
Capture git status/diff and preserve other work; no blind auto-add of unrelated
files. Claimed lane authority still governs every file.

Anticipated Paths comes from Architect's persisted task body and is read-only
for Conduct/Engineer/Tester. Omit absent block, no placeholder/new storage.
Uncovered required edits widen via existing claim discipline; cross-task or
new-surface scope routes pinned authoring repair. Claims never narrow scope.

## Exact task and parent QA

```text
yoke workflow-item epic-task review-seed --epic PREFIX-N --task-num {task_num}
yoke workflow-item epic-task review-insert --epic PREFIX-N --task-num {task_num} --verdict PASS --body-file {REVIEW_FILE}
yoke qa requirement list --epic PREFIX-N --json
yoke qa requirement list --item PREFIX-N --json
yoke qa run list --requirement-id {requirement_id}
```

Seed once idempotently before review. Insert ACTUAL verdict with per-AC body
reuses that requirement; no duplicate requirement or manual qa run add for task
review. Parent requirements remain distinct. Execute each materialized native
case with its exact subject; task passes and simulation do not blanket-credit
command/Browser cases. Aggregate evidence may satisfy only the requirement's
declared evidence policy with a current claimed candidate and real results.

Never auto-waive blocking QA. Unavailable target/infrastructure HALTs for
operator repair or explicit waiver through registered help; authenticated
operator source/force only when actually authorized. Nonblocking waiver follows
its own allowed surface and records rationale. Raw DB/router mutation is not
normal flow; never substitute it when the registered command refuses.

Keep required result/evidence, exact run/requirement ids and candidate currency.
Capture/review pending is not pass. The simulation owner alone persists its
typed report receipt. Completed parent handoff still verifies every owed gate.
