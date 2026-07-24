# Next Tickets After YOK-1113 / YOK-1115

## Summary

File 6 follow-up tickets.

- 2 are `do now` defects because they compromise the truth model that `YOK-1113` was meant to solidify.
- 4 are `do soon` conduct/runtime tickets because they caused most of the session pain and are likely to recur.

Verification already performed:

- `sh .claude/skills/yoke/scripts/tests/test-status-lifecycle.sh`
- `sh .claude/skills/yoke/scripts/tests/test-approval-vocabulary.sh`
- `sh .claude/skills/yoke/scripts/tests/test-canonical-truth-drift.sh`
- `pytest yoke/api/test_api.py`

All pass, but several tests and doctor checks currently codify compatibility behavior that should be removed in follow-up work.

## Ticket Queue

| When | Title |
|---|---|
| Now | API approval endpoint must advance authoritative deployment state |
| Now | Make canonical lifecycle registry, docs, and runtime agree after YOK-1113 |
| Soon | Conduct should own epic QA gate lifecycle end-to-end |
| Soon | Dispatch chain advancement needs a first-class helper |
| Soon | Harden conduct subagent prompt and tool discipline |
| Soon | Reduce conduct noise from board rebuild contention and stale background-task residue |

## Traceability

- Numbered conduct issues map as: `1->5`, `2->3`, `3->3`, `4->3`, `5->5`, `6->5`, `7->4`, `8->3`, `9->3`, `10->5`, `11->6`, `12->6`, `13->3`, `14->3`, `15->4`, `16->3`.
- Truth-model tickets `1-2` come from the canonical registry/runtime review rather than the numbered conduct-issue list.
- Consolidation note: prior plan clusters `T1+T2+T5 -> 3` and `T4+T6 -> 5`.

## Ticket Specs

### 1. API approval endpoint must advance authoritative deployment state
**When:** Now

**Problem**
`approval-vocabulary.sh` says `deployment_runs.current_stage` is authoritative and `items.deploy_stage` is a cache mirror, but `yoke/api/main.py` only checks `items.deploy_stage == 'awaiting-approval'` and then sets `items.status = 'release'`. It does not advance the authoritative run state or clear the cached halt state.

**Evidence**
- `yoke/api/main.py`
- `.claude/skills/yoke/scripts/approval-vocabulary.sh`
- `yoke/api/test_api.py`

**Root cause**
`YOK-1113` froze vocabulary but the API implementation stayed item-centric instead of run-centric.

**Desired fix**
Make approval advance the authoritative deployment-run stage and keep `items.deploy_stage` / `items.status` in sync as part of the same transition.

**Non-goal**
Do not broaden this ticket into the full stale re-approval / idempotency design space. If that needs special semantics, handle it in `YOK-1112`.

**Acceptance criteria**
- Approval advances run state and item mirror state atomically.
- Cached halt state is advanced or cleared coherently in the same operation.
- API tests assert `deployment_runs.current_stage`, `items.deploy_stage`, and `items.status` together.

### 2. Make canonical lifecycle registry, docs, and runtime agree after YOK-1113
**When:** Now

**Problem**
Live conduct/runtime surfaces still branch on retired terms like `in_progress`, `completed`, `merged`, and `validation`. `rebuild-board.sh` and `yoke/api/main.py` still normalize retired aliases in current behavior. `doctor.sh` and the new truth tests allow or require those compatibility sites. Separately, `status-lifecycle.sh` includes `release` in `STATUS_TASK_ALL`, while `yoke/.yoke/docs/qa-platform.md` says epic tasks do not independently enter `release`.

**Evidence**
- `.claude/skills/yoke/conduct/single-item.md`
- `.claude/skills/yoke/conduct/dispatch-context.md`
- `.claude/skills/yoke/conduct/batch-flow.md`
- `.claude/skills/yoke/scripts/rebuild-board.sh`
- `yoke/api/main.py`
- `.claude/skills/yoke/scripts/status-lifecycle.sh`
- `.claude/skills/yoke/scripts/doctor.sh`
- `.claude/skills/yoke/scripts/tests/test-status-lifecycle.sh`
- `.claude/skills/yoke/scripts/tests/test-canonical-truth-drift.sh`
- `yoke/.yoke/docs/qa-platform.md`

**Root cause**
`YOK-1113` froze the canonical vocabulary, but registry, docs, tests, and live surfaces were not reconciled as one sweep.

**Desired fix**
Make one explicit decision about whether epic tasks can enter `release`, then align registry, docs, tests, board logic, API behavior, and conduct/runtime docs to that decision. Remove retired alias handling from live current-behavior surfaces. Keep retired terms only in archival/recovery/history material or true one-time migrations.

**Acceptance criteria**
- No live current-behavior surface accepts or branches on retired delivery statuses.
- Registry, docs, and tests agree on the epic-task lifecycle, including the `release` question.
- Conduct/runtime docs use canonical statuses only.
- Doctor/tests fail if retired statuses or lifecycle-scope drift reappear in live surfaces.
- Any remaining old rows/callers are handled as migration bugs, not runtime compatibility.

### 3. Conduct should own epic QA gate lifecycle end-to-end
**When:** Soon

**Problem**
During the `YOK-1113` conduct session, validate transitions failed because no `qa_requirements` existed, passed transitions failed because no passing `qa_runs` existed, duplicate requirements created extra blockers, and parent `ac_verification` / simulation requirements had to be satisfied manually.

**Evidence**
- Session issues 2, 3, 4, 8, 9, 13, 14, 16
- `.claude/skills/yoke/conduct/single-item.md`
- `.claude/skills/yoke/conduct/batch-flow.md`
- `.claude/skills/yoke/conduct/dispatch-context.md`
- `.claude/skills/yoke/scripts/yoke-db.sh qa`
- `yoke/.yoke/docs/qa-platform.md`

**Root cause**
QA gating exists, but conduct does not own requirement seeding, run recording, and parent-gate satisfaction for epic work.

**Desired fix**
Seed task-level review requirements idempotently, record tester PASS as `qa_runs`, auto-satisfy parent `ac_verification` and simulation requirements when evidence exists, and fold the operator documentation into the same fix.

**Acceptance criteria**
- Standard epic conduct requires zero manual `yoke-db.sh qa` recovery calls.
- Retry paths do not create duplicate blocking requirements.
- Parent epic `passed` can be reached from normal conduct evidence.

**Implementation note**
Prefer one thin shared helper surface now so this can later move cleanly into the Python service core in `YOK-1112`.

### 4. Dispatch chain advancement needs a first-class helper
**When:** Soon

**Problem**
The operator guessed `dispatch-chain-advance`, it failed, and raw SQL became the fallback. `yoke-db.sh epic` exposes `dispatch-chain-get`, `dispatch-chain-update`, and `dispatch-chain-list`, but not the intuitive common operation.

**Evidence**
- Session issues 7 and 15
- `.claude/skills/yoke/scripts/yoke-db.sh epic`
- `.claude/skills/yoke/scripts/tests/test-yoke-db.sh epic`

**Root cause**
Common advancement behavior is hidden behind a generic update interface.

**Desired fix**
Add a supported chain-advance helper and switch conduct/autofix flows to it.

**Acceptance criteria**
- No conduct flow uses raw SQL to advance dispatch chains.
- Tests cover normal advancement, end-of-queue, and missing-chain behavior.
- Conduct docs reference the supported helper, not field-level mutation.

### 5. Harden conduct subagent prompt and tool discipline
**When:** Soon

**Problem**
The session saw repeated read token-limit failures, malformed JSON/sqlite mistakes, one path-resolution `127`, and tester prompt diff truncation.

**Evidence**
- Session issues 1, 5, 6, 10
- `.claude/agents/yoke-engineer.md`
- `.claude/agents/yoke-tester.md`
- `.claude/skills/yoke/conduct/dispatch-context.md`
- `.claude/skills/yoke/conduct/single-item.md`

**Root cause**
Prompt and agent discipline are still too loose around large-file reads, raw DB work, path reuse, and faithful diff handoff.

**Desired fix**
Add explicit read chunking guidance, strengthen wrapper-over-raw-sqlite rules, require absolute script paths in every call, and forbid ellipsized diffs in tester prompts.

**Acceptance criteria**
- Engineer/tester prompts stop failing on predictable file-size/path/DB discipline issues.
- Testers always get faithful diff context, inline or via temp file.
- Conduct prompts do not rely on shell vars persisting across calls.

### 6. Reduce conduct noise from board rebuild contention and stale background-task residue
**When:** Soon

**Problem**
Rapid conduct transitions produced `BOARD.md.lock` timeout warnings and stale background-task notifications after the work was effectively done.

**Evidence**
- Session issues 11 and 12

**Root cause**
Conduct performs many fast status transitions and supporting background activity without batching/debouncing those side effects.

**Desired fix**
Reduce unnecessary board rebuild frequency during conduct and investigate suppressing or scoping irrelevant background-task residue. This stays behind the correctness tickets, but it is already recurring enough to keep in the near-term queue.

**Acceptance criteria**
- Normal conduct sessions no longer spam board lock timeout warnings.
- Stale background task notifications do not surface after a clean conduct path.

## Ordering Guidance

- Do tickets `1-2` before `YOK-1112` service-core work so Python does not inherit compromised truth.
- Do tickets `3-5` next, but implement them as thin helper surfaces rather than more sprawling shell-native business logic.
- Do ticket `6` after `3-5`; it is promoted to `Soon` because the noise already repeated, but it still comes after the correctness/conduct fixes unless it starts materially blocking sessions.

## Assumptions

- `YOK-1115` is considered correctly landed; no follow-up ticket is needed now.
- Retired delivery terms are only acceptable in archival/recovery/history material.
- If old persisted rows or old callers still exist, that is a migration defect, not a runtime compatibility justification.
