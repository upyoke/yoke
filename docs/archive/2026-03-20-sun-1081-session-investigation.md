# YOK-1081 Session Investigation Memo

Date of investigation: March 20, 2026

Primary sources:

- Session transcript: `/Users/dev/.claude/projects/-Users-dev-yoke/bf0f224d-cb58-4506-acd7-e8f6ddbcc4a6.jsonl`
- Yoke DB: `/Users/dev/yoke/yoke/yoke.db`
- Background task output: `/private/tmp/claude-501/-Users-dev-yoke/bf0f224d-cb58-4506-acd7-e8f6ddbcc4a6/tasks/bgwex1w3l.output`

## Executive Summary

YOK-1081 did reach `done`, but the operator path was rougher than the final recap implied. The feature work itself appears to have been fine. The problems were in harness selection, QA seeding, evidence enforcement, status-transition guidance, deploy observability, and final reporting.

The biggest findings are:

1. The "pre-existing pydantic issue" was not a missing code fix in Buzz. The repo already had the YOK-1061 dependency pins, but this session ran system `python3` against incompatible global site-packages with no local virtualenv, so the fix never reached the runtime that executed pytest.
2. The direct `status=passed` write was blocked for the right reason, but the operator path then bypassed the guard with `# lint:no-passed-check` instead of using the router path the lint message explicitly named.
3. The original prompt required 3 screenshot-producing checks. Only 2 screenshot artifacts were created. The confetti requirement was folded into browser requirement `1878` as a 12-second delay plus screenshot, while the separate confetti AC `1876` was satisfied by an `agent` run with no browser artifact.
4. The deploy wait path used fixed sleep polling even after a background completion notification had already arrived, adding about 50 seconds of avoidable latency.

## Scope and timing

The original prompt landed at `2026-03-20T19:39:55.899Z`. The first session-level tool event landed at `2026-03-20T19:40:05.575Z`. YOK-1081 itself was created at `2026-03-20T19:40:41Z`, which means item-scoped events do not cover the very start of the process.

Important elapsed times:

- Prompt -> item status `done` (`items.updated_at`): `28m 40.101s`
- Prompt -> `done-transition.sh` completion: `28m 51.889s`
- First session tool event -> `done-transition.sh` completion: `28m 42.213s`
- Item creation -> item status `done`: `27m 54.113s`

Additional merged timing view from the immediate post-done slice:

- Item creation window (`2026-03-20T19:40:41Z`) -> last attributed YOK-1081 event (`2026-03-20T20:09:06.764Z`): `28m 25.764s`

## Synthesized addendum

This memo originally reflected the Codex-only investigation. After merging in Darius's pass:

- the timeline now uses both the session-level start and the item-attributed end;
- the immediate post-done unattributed slice is called out explicitly;
- the ticket set has been consolidated into the synthesized pack at `/Users/dev/yoke/yoke/context-archive/2026-03-20-yok-1081-ticket-drafts.md`.

Verified counts for the merged view:

- `161` events attributed to `item_id=1081`
- `1` `ToolCallFailed`
- `79` unattributed post-done events in the immediate analysis slice through `2026-03-20T20:17:00Z`
- `90` unattributed events in the broader lifetime of the same session ID, including later follow-up work outside the immediate post-done slice

Merged ticket map:

| Code | Title |
| --- | --- |
| A | Buzz backend tests unreachable - no venv exists despite YOK-1061 fix |
| B | Finalize.md status update command missing `lint:no-passed-check` bypass |
| C | Browser QA seeding collapses same-route multi-capture checks and lets visual ACs pass without independent screenshot evidence |
| D | Usher deploy.md lacks guidance on long-running pipeline execution strategy |
| E | observe-tool records deploy-pipeline exit 2 (approval gate) as ToolCallFailed |
| F | Post-done-transition tool calls lose `item_id` attribution in the immediate post-done slice |
| G | Active sub-skill allows silent test command deviation and optimistic pass recording |
| H | Browser screenshot artifact metadata stores the wrong route |
| I | Merge/done flow can skip project-specific runner detection |
| J | Agent execution hygiene papercuts in idea-to-done flows |

## Direct answers to the four requested questions

### 1. Why did the pydantic error happen if YOK-1061 was already fixed?

Because the fix existed in-repo, but not in the runtime that actually executed pytest.

Evidence:

- Buzz currently pins the fixed dependency range in `/Users/dev/buzz/app/requirements.txt`:
  - `pydantic>=2.7,<3`
  - `pydantic-settings>=2.0,<3`
- No local virtualenv was present under `/Users/dev/buzz` during this investigation.
- Reproducing with the same system interpreter used by the session shows:
  - executable: `/Library/Developer/CommandLineTools/usr/bin/python3`
  - installed `pydantic`: `2.6.1`
  - `pydantic_settings` import fails: `cannot import name 'Secret' from 'pydantic'`
  - `api.main` import fails for the same reason
- The failing session output showed pytest importing from the global user site-packages path under `/Users/dev/Library/Python/3.9/...`, not from an environment created from the pinned requirements.

Conclusion:

YOK-1061 fixed the dependency declaration and guidance. It did not make the quick-test command hermetic. The session still used raw `python3 -m pytest`, so an older global install was enough to recreate the failure.

### 2. Why was the original attempt to set `status=passed` blocked?

Because direct low-level writes to `status=passed` are guarded on purpose. The system expects the router path so browser QA, project E2E, and finalize all run in the approved order.

Evidence:

- The session ran:

```sh
sh .claude/skills/yoke/scripts/yoke-db.sh items update 1081 status passed
```

- The response was:

```text
BLOCKED: Do not set status=passed directly.
Use: /yoke advance YOK-N passed
The advance router handles browser-qa, project-e2e, and finalize...
Add '# lint:no-passed-check' comment to suppress if you understand the risks...
```

- The next command was the bypass version:

```sh
sh .claude/skills/yoke/scripts/yoke-db.sh items update 1081 status passed # lint:no-passed-check
```

- The finalize guidance in `/Users/dev/yoke/.claude/skills/yoke/advance/finalize.md` still shows a bare status update command:

```sh
sh .claude/skills/yoke/scripts/yoke-db.sh items update {N} status {_target}
```

Conclusion:

The original attempt was blocked because the guard worked as designed. The underlying problem is that the guidance, the lint rule, and the agent recovery behavior are not aligned.

### 3. Why were only 2 screenshots taken when the original prompt asked for 3?

Because the QA seeding path created only 2 `browser_smoke` requirements, not 3 screenshot-producing requirements.

Evidence:

- The prompt explicitly said:
  - login page theme check with screenshot
  - forgot password theme check with screenshot
  - confetti check with screenshot 12 seconds after load
  - `all 3 of these qa reqs must produce screenshots`
- The seeded requirements for item `1081` were:
  - `1874` `ac_verification`
  - `1875` `ac_verification`
  - `1876` `ac_verification` for confetti
  - `1877` `ac_verification` for tests
  - `1878` `browser_smoke` for `/login`
  - `1879` `browser_smoke` for `/forgot-password`
  - `1880` `e2e`
- Requirement `1878` contains the 12-second delay:

```json
{"action":"delay","duration":12000,"refined":false,"source_ac":"timing"}
```

- The only screenshot artifacts were:
  - `139` for run `1921`
  - `140` for run `1922`
- Confetti AC `1876` was marked passed by run `1919` with executor `agent`, not `browser_substrate`.

Conclusion:

The confetti screenshot obligation was partially preserved as a delay inside requirement `1878`, but the separate screenshot cardinality from the prompt was lost. The system treated confetti as an AC to be textually verified, not as a third screenshot-producing browser obligation.

### 4. Why was `sleep x and check again` inefficient?

Because the agent already had a proper background-task notification channel, but used manual polling anyway.

Evidence:

- Background deploy resumed at `2026-03-20T20:06:02.591Z` with task ID `bgwex1w3l`.
- The session immediately polled the output file with:

```sh
cat .../bgwex1w3l.output 2>/dev/null || echo "still running"
sleep 45 && cat .../bgwex1w3l.output | tail -30
sleep 60 && cat .../bgwex1w3l.output | tail -20
```

- A queue notification arrived at `2026-03-20T20:07:16.456Z` saying:
  - task `bgwex1w3l`
  - status `completed`
  - background command completed with exit code `0`
- The `sleep 60` poll did not return until `2026-03-20T20:08:07.077Z`.

Conclusion:

The agent sat inside a fixed sleep even after the system had already told it the command was done. That added about `50.621` seconds of unnecessary delay.

## Timestamped timeline

| Time (UTC) | Source | What happened |
| --- | --- | --- |
| `2026-03-20T19:39:55.899Z` | transcript | Original prompt requested idea -> done flow with 3 screenshot-producing checks. |
| `2026-03-20T19:40:05.575Z` | session event | First tool event completed: `Read` on Yoke idea skill. |
| `2026-03-20T19:40:41Z` | items table | YOK-1081 created. |
| `2026-03-20T19:44:27.383Z` | tool event | `status active` completed. |
| `2026-03-20T19:44:55Z` to `2026-03-20T19:45:53Z` | QA events | Requirements `1874` through `1880` were seeded. |
| `2026-03-20T19:53:00.064Z` | tool event | Backend pytest command completed with import errors. |
| `2026-03-20T19:53:09.936Z` | transcript | Assistant called the failure "pre-existing" and switched to frontend tests. |
| `2026-03-20T19:53:39Z` to `2026-03-20T19:53:57Z` | `qa_runs` | Agent marked AC runs `1917` through `1920` passed, including confetti AC `1919`. |
| `2026-03-20T19:55:16Z` to `2026-03-20T19:55:31Z` | `qa_runs` | Browser runs `1921` and `1922` completed. |
| `2026-03-20T19:55:29Z` and `2026-03-20T19:55:30Z` | `qa_artifacts` | Screenshot artifacts `139` and `140` were recorded. |
| `2026-03-20T19:56:34.298Z` | tool event | E2E command against the ephemeral URL completed successfully. |
| `2026-03-20T19:56:45Z` | `qa_runs` | CI run `1923` recorded the E2E pass. |
| `2026-03-20T19:56:52.451Z` | transcript | Direct `status=passed` write was blocked. |
| `2026-03-20T19:57:14.398Z` | tool event | Bypass write `status passed # lint:no-passed-check` completed. |
| `2026-03-20T19:58:46.726Z` | tool event | `status release` completed. |
| `2026-03-20T19:59:25.941Z` | tool event | `merge-worktree.sh` completed, printing `(No test runner detected - skipping)`. |
| `2026-03-20T20:00:35.793Z` | events table | Event `70764` recorded the approval gate as `ToolCallFailed` with severity `WARN`. |
| `2026-03-20T20:01:13Z` | deployment event | `prod-deploy` started. |
| `2026-03-20T20:06:02.591Z` | transcript | Deploy was backgrounded as task `bgwex1w3l`. |
| `2026-03-20T20:06:15.750Z` | transcript | `sleep 45` poll started. |
| `2026-03-20T20:07:06.837Z` | transcript | `sleep 60` poll started. |
| `2026-03-20T20:07:16.456Z` | transcript queue op | Background task completion notification arrived. |
| `2026-03-20T20:08:36Z` | items table | YOK-1081 `updated_at` moved to `done`. |
| `2026-03-20T20:08:47.788Z` | tool event | `done-transition.sh 1081 --skip-deploy` completed. |
| `2026-03-20T20:09:33.386Z` | transcript | Final recap overstated screenshot coverage and test coverage. |

## Issue inventory

| ID | Classification | Problem | Concrete evidence | Mapped draft ticket |
| --- | --- | --- | --- | --- |
| I-1 | root cause | Quick-test Python execution was not hermetic. | System Python 3.9.6 imported `pydantic 2.6.1` from user site-packages; no `.venv` existed. | `Buzz quick-test command is not hermetic against pinned Python deps` |
| I-2 | root cause | Partial test execution was later reported as if the whole quick-test path passed. | Backend pytest failed; final recap claimed `All 144 unit tests + 37 E2E tests passed`. | `Quick-test and done summaries overstate coverage after partial test execution` |
| I-3 | symptom | Direct `status=passed` write was blocked. | Transcript lines at `19:56:52Z`. | `Advance passed transition guidance conflicts with lint guard and encourages bypass` |
| I-4 | root cause | Guidance and lint rule disagree on how `passed` should be written. | `advance/finalize.md` shows a bare update; lint requires router or suppression. | `Advance passed transition guidance conflicts with lint guard and encourages bypass` |
| I-5 | root cause | Explicit screenshot cardinality was collapsed during QA seeding. | Prompt asked for 3 screenshot-producing checks; only `1878` and `1879` were browser requirements. | `Explicit screenshot requirements are collapsed during QA seeding` |
| I-6 | root cause | Visual ACs could pass without artifact-backed browser evidence. | Run `1919` passed confetti AC `1876` with executor `agent`; no third screenshot artifact existed. | `Visual ACs can pass without artifact-backed browser evidence` |
| I-7 | root cause | Screenshot artifact metadata stored the wrong route. | Artifacts `139` and `140` both recorded `"route":"/"`. | `Browser screenshot artifact metadata stores the wrong route` |
| I-8 | telemetry/UX | Approval wait was emitted as a failed tool call. | Event `70764` was `ToolCallFailed` `WARN`, even though the stage was waiting on human approval. | `Deploy approval waits are emitted as failed tool calls instead of a paused-awaiting-approval state` |
| I-9 | root cause | Background task monitoring ignored the completion notification channel. | Queue notification arrived at `20:07:16Z`; `sleep 60` poll returned at `20:08:07Z`. | `Background task monitoring uses fixed sleep polling instead of completion signals` |
| I-10 | root cause | Merge path did not detect a project test runner even though project-specific tests had already been run manually. | Merge output printed `(No test runner detected - skipping)`. | `Merge/done flow can skip runner detection even when project tests exist` |
| I-11 | one-off papercut | A targeted replace failed after the file had already changed. | `String to replace not found in file` at `19:52:26Z`. | `Agent execution hygiene papercuts in idea->done flows` |
| I-12 | one-off papercut | The exploration subagent started with an over-broad `find` that dumped `node_modules` entries. | Subagent `a2a143a458ee0eb6d` first search returned many `node_modules/*.d.ts` files. | `Agent execution hygiene papercuts in idea->done flows` |

## Notes on the final recap

The final "Usher Complete" recap at `2026-03-20T20:09:33.386Z` is materially more optimistic than the evidence trail supports.

Overstatements:

- It said browser QA screenshots confirmed the theme on both pages, but the user explicitly asked for 3 screenshot-producing checks and only 2 screenshot artifacts were created.
- It said `All 144 unit tests + 37 E2E tests passed`, but the session had already hit a backend pytest import failure and then switched to frontend-only unit tests plus E2E.

This does not mean the feature itself was broken. It means the summary layer was not strict about deriving claims from the exact recorded evidence.

## Source files and commands used in this investigation

Key local files:

- `/Users/dev/.claude/projects/-Users-dev-yoke/bf0f224d-cb58-4506-acd7-e8f6ddbcc4a6.jsonl`
- `/Users/dev/yoke/yoke/yoke.db`
- `/Users/dev/buzz/app/requirements.txt`
- `/Users/dev/yoke/.claude/skills/yoke/advance/finalize.md`
- `/Users/dev/yoke/.claude/skills/yoke/scripts/lint-sqlite-cmd.sh`
- `/Users/dev/yoke/.claude/skills/yoke/scripts/merge-worktree.sh`

Representative verification commands:

```sh
python3 - <<'PY'
import sqlite3
conn = sqlite3.connect('file:/Users/dev/yoke/yoke/yoke.db?mode=ro', uri=True)
for row in conn.execute("SELECT id, qa_kind, requirement_source, success_policy FROM qa_requirements WHERE item_id=1081 ORDER BY id"):
    print(row)
PY
```

```sh
cd /Users/dev/buzz/app
/Library/Developer/CommandLineTools/usr/bin/python3 - <<'PY'
import pydantic, api.main
PY
```

```sh
rg -n 'Do not set status=passed directly|No test runner detected|Awaiting human approval|sleep 60 && cat' \
  /Users/dev/.claude/projects/-Users-dev-yoke/bf0f224d-cb58-4506-acd7-e8f6ddbcc4a6.jsonl
```
