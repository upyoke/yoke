# YOK-1081 Ticket Draft Pack

This pack synthesizes the earlier Codex draft set with Darius's narrower ticket proposal. The result keeps Darius's A-G backbone, carries forward the extra route-metadata / merge-runner / papercut follow-ups, and corrects the event-count nuance around unattributed post-done work.

Nothing below has been filed yet.

## Session timeline

- First session-level tool event: `2026-03-20T19:40:05.575Z`
- First YOK-1081-attributed event / item creation window: `2026-03-20T19:40:41Z`
- Active + worktree ready: `2026-03-20T19:44:27.383Z`
- Implementation complete + commit: `2026-03-20T19:52:39.688Z`
- Backend pytest failure + frontend fallback: `2026-03-20T19:53`
- Browser QA and E2E recorded: `2026-03-20T19:55` to `2026-03-20T19:56`
- Merge complete: `2026-03-20T19:59:25.941Z`
- Deploy pipeline started: `2026-03-20T20:00`
- Prod + smoke complete: `2026-03-20T20:07:15Z`
- Done-transition complete: `2026-03-20T20:08:47.788Z`
- Last YOK-1081-attributed event in the immediate session slice: `2026-03-20T20:09:06.764Z`

Important durations:

- Prompt -> item `done`: `28m 40.101s`
- Prompt -> `done-transition.sh` complete: `28m 51.889s`
- Idea creation window (`19:40:41Z`) -> last attributed event (`20:09:06.764Z`): `28m 25.764s`

## Event counts

- `161` events attributed to `item_id=1081`
- `1` `ToolCallFailed`
- `79` unattributed post-done events in the immediate follow-on slice from `2026-03-20T20:11:16.125Z` through `2026-03-20T20:17:00Z`
- `90` unattributed session events in the full session lifetime, including later follow-up activity outside the immediate post-done analysis window

## Summary table

| Code | Title | Project | Priority | Root cause |
| --- | --- | --- | --- | --- |
| A | Buzz backend tests unreachable - no venv exists despite YOK-1061 fix | buzz | high | Repo pins exist, but the runtime environment is never bootstrapped before pytest runs. |
| B | Finalize.md status update command missing `lint:no-passed-check` bypass | yoke | medium | Finalize template and lint guard disagree on the supported `passed` path. |
| C | Browser QA seeding collapses same-route multi-capture checks and lets visual ACs pass without independent screenshot evidence | yoke | medium | One-browser-requirement-per-route seeding plus loose visual-evidence rules erase the user's screenshot cardinality. |
| D | Usher deploy.md lacks guidance on long-running pipeline execution strategy | yoke | low | Docs leave agents to improvise backgrounding and polling for multi-minute deploy steps. |
| E | observe-tool records deploy-pipeline exit 2 (approval gate) as ToolCallFailed | yoke | low | Structured non-zero exits are treated like errors in the hook layer. |
| F | Post-done-transition tool calls lose `item_id` attribution in the immediate post-done slice | yoke | low | Main-session attribution only knows marker or single-active-item fallback. |
| G | Active sub-skill allows silent test command deviation and optimistic pass recording | yoke | medium | No waiver/fail-record requirement exists for quick/full command failures, only for E2E skip cases. |
| H | Browser screenshot artifact metadata stores the wrong route | yoke | low | Artifact metadata defaults to `/` instead of the scenario route. |
| I | Merge/done flow can skip project-specific runner detection | yoke | low | Merge runner detection only knows generic `npm test` / `make test` paths. |
| J | Agent execution hygiene papercuts in idea-to-done flows | yoke | low | Search and edit defaults still allow avoidable transcript noise. |

## Ticket A

**Title:** Buzz backend tests unreachable - no venv exists despite YOK-1061 fix
**Project:** buzz | **Type:** issue | **Priority:** high

### Body

# Buzz backend tests unreachable - no venv exists despite YOK-1061 fix

## Problem

YOK-1061 pinned `pydantic>=2.7,<3` in `app/requirements.txt` and added local Python setup guidance, but the working Python environment was never actually provisioned. The registered quick-test path still runs raw `python3 -m pytest`, which resolves to system Python 3.9 with incompatible global user-site packages.

## Evidence (YOK-1081 session, 2026-03-20)

- Backend quick-test command completed at `2026-03-20T19:53:00.064Z`:

```sh
cd /Users/dev/buzz/.worktrees/YOK-1081 && cd app && python3 -m pytest tests/ -k "not live" 2>&1 | tail -20
```

- The failure included:

```text
from pydantic import BaseModel, Json, RootModel, Secret
```

- Current local reproduction with the same interpreter shows:
  - executable: `/Library/Developer/CommandLineTools/usr/bin/python3`
  - `pydantic=2.6.1`
  - `pydantic_settings import failed: cannot import name 'Secret' from 'pydantic'`
  - `api.main import failed: cannot import name 'Secret' from 'pydantic'`
- `/Users/dev/buzz/app/.venv` does not exist.
- `/Users/dev/buzz/app/requirements.txt` already contains the fixed pins:
  - `pydantic>=2.7,<3`
  - `pydantic-settings>=2.0,<3`

## Root cause

YOK-1061 fixed the declared dependency versions, but not the runtime bootstrapping path. Buzz's Yoke-facing setup path still only provisions Node-side dependencies, so backend tests can run against whatever Python environment happens to be installed on the machine.

## Acceptance criteria

- [ ] Create a supported Python virtualenv path for Buzz, preferably `app/.venv`.
- [ ] Update the Buzz Yoke `setup_command` to create the venv and install `requirements.txt` before tests run.
- [ ] Update `test_command_quick` and `test_command_full` to activate the venv (or otherwise force the hermetic interpreter) before pytest.
- [ ] Verify the full quick-test path can execute end-to-end with both backend and frontend steps.
- [ ] Evaluate whether `validate-test-commands.sh` should also validate environment bootstrapping, not just command existence.

## Template propagation

Stance: `project-and-template`

If the webapp template exposes `requirements.txt`, the template-level setup guidance should include a Python bootstrapping pattern that downstream projects can inherit.

## Ticket B

**Title:** Finalize.md status update command missing `lint:no-passed-check` bypass
**Project:** yoke | **Type:** issue | **Priority:** medium

### Body

# Finalize.md status update command missing `lint:no-passed-check` bypass

## Problem

`advance/finalize.md` documents the status update as:

```sh
sh .claude/skills/yoke/scripts/yoke-db.sh items update {N} status {_target}
```

When `{_target}` is `passed`, `lint-sqlite-cmd.sh` check 12 blocks that exact command. Finalize runs inside the advance router, so it is already on the legitimate path. The template is incomplete.

## Evidence (YOK-1081 session, 2026-03-20)

- The session executed the documented direct form at `2026-03-20T19:56:52.375Z`.
- Lint blocked it with:

```text
BLOCKED: Do not set status=passed directly.
Use: /yoke advance YOK-N passed
...
Add '# lint:no-passed-check' comment to suppress if you understand the risks...
```

- The agent recovered by running:

```sh
sh .claude/skills/yoke/scripts/yoke-db.sh items update 1081 status passed # lint:no-passed-check
```

- The conduct pipeline already documents the bypassed form for its intentional PASS path.

## Root cause

The finalize template was never updated to match the lint guard that now protects direct `passed` writes.

## Files to modify

- `/Users/dev/yoke/.claude/skills/yoke/advance/finalize.md`

## Acceptance criteria

- [ ] Update the finalize.md step-6 command to include `# lint:no-passed-check`.
- [ ] Verify advance-to-passed completes without the extra blocked round-trip.
- [ ] Keep the stronger "use the router, not direct DB writes" guidance in `advance/implementing/SKILL.md`.

## Ticket C

**Title:** Browser QA seeding collapses same-route multi-capture checks and lets visual ACs pass without independent screenshot evidence
**Project:** yoke | **Type:** issue | **Priority:** medium

### Body

# Browser QA seeding collapses same-route multi-capture checks and lets visual ACs pass without independent screenshot evidence

## Problem

When multiple screenshot-producing asks target the same route but require different capture strategies, the browser QA seeding flow currently creates only one browser requirement per route. The timing-specific ask is folded into that route's step list instead of becoming a separate browser-backed requirement. At the same time, the leftover visual AC can still pass through `agent` review with no screenshot artifact.

## Evidence (YOK-1081 session, 2026-03-20)

The prompt explicitly asked for three screenshot-producing checks:

- login page theme screenshot
- forgot-password theme screenshot
- confetti screenshot 12 seconds after page load

What the system created:

- `1878` `browser_smoke` for `/login`, with a `12000` ms delay and screenshot
- `1879` `browser_smoke` for `/forgot-password`
- `1876` `ac_verification` for confetti

What the system recorded:

- only two screenshot artifacts: `139` and `140`
- confetti AC `1876` passed via `qa_run 1919` with `executor_type='agent'`

This means the confetti capture survived only as an embedded step inside `1878`, not as its own screenshot-backed QA obligation.

## Root cause

- `advance/implementing/SKILL.md` iterates over routes and creates one `browser_smoke` per route.
- There is no separate notion of "distinct capture strategies for the same route".
- Visual ACs outside `browser_smoke` / `browser_diff` are still allowed to pass through plain agent review even when the prompt required screenshot evidence.

## Files to modify

- `/Users/dev/yoke/.claude/skills/yoke/advance/implementing/SKILL.md`
- Possibly `/Users/dev/yoke/.claude/skills/yoke/advance/browser-qa.md` and the done-gate evidence rules

## Acceptance criteria

- [ ] When multiple same-route visual checks require different timing or capture strategies, create separate browser-backed requirements.
- [ ] Each user-specified screenshot check produces its own screenshot artifact.
- [ ] Visual ACs that explicitly require screenshot evidence cannot pass via `executor_type='agent'` alone.
- [ ] Preserve current behavior for simple one-route / one-capture cases.

## Ticket D

**Title:** Usher deploy.md lacks guidance on long-running pipeline execution strategy
**Project:** yoke | **Type:** issue | **Priority:** low

### Body

# Usher deploy.md lacks guidance on long-running pipeline execution strategy

## Problem

`usher/deploy.md` shows `deploy-pipeline.sh` as a straightforward blocking command, but it does not explain that the command can run for several minutes or how agents should handle that. In YOK-1081, the agent improvised a background-task pattern, then manually sleep-polled the output file instead of waiting on the built-in completion notification.

## Evidence (YOK-1081 session, 2026-03-20)

- Background task `bgwex1w3l` was created at `2026-03-20T20:06:02.591Z`.
- The agent then ran:

```sh
cat .../bgwex1w3l.output 2>/dev/null || echo "still running"
sleep 45 && cat .../bgwex1w3l.output | tail -30
sleep 60 && cat .../bgwex1w3l.output | tail -20
```

- A proper task notification arrived at `2026-03-20T20:07:16.456Z`, but the `sleep 60` poll did not return until `2026-03-20T20:08:07.077Z`.

Two useful ways to quantify the waste:

- About `105` seconds were spent inside polling commands.
- About `50.621` seconds elapsed after the completion notification had already arrived.

## Root cause

This is partly an agent behavior problem and partly a docs gap. `usher/deploy.md` does not tell the agent whether to stay in the foreground or, if backgrounding is used, to trust the notification channel and not poll.

## Files to modify

- `/Users/dev/yoke/.claude/skills/yoke/usher/deploy.md`

## Acceptance criteria

- [ ] Add explicit guidance to step `8c9` for long-running deploy-pipeline calls.
- [ ] If backgrounding is recommended, say "await task notification, do not poll".
- [ ] Verify a future usher deploy does not use fixed `sleep N && check again` loops.

## Ticket E

**Title:** observe-tool records deploy-pipeline exit 2 (approval gate) as ToolCallFailed
**Project:** yoke | **Type:** issue | **Priority:** low

### Body

# observe-tool records deploy-pipeline exit 2 (approval gate) as ToolCallFailed

## Problem

`deploy-pipeline.sh` uses exit code `2` as structured control flow for "awaiting approval", but the hook layer treats that non-zero exit as a failed tool call and logs it as `ToolCallFailed`.

## Evidence (YOK-1081 session, 2026-03-20)

- Event `70764` at `2026-03-20T20:00:35.793Z` was logged as:
  - severity: `WARN`
  - event name: `ToolCallFailed`
- The embedded error text was:

```text
Awaiting human approval for stage 'approve-deploy'
```

- This was the only `ToolCallFailed` in the immediate session slice, even though it was not a real execution error.

## Root cause

`observe-tool.sh` treats `PostToolUseFailure` uniformly, and Bash non-zero exits currently flow through that path without a distinction between "expected structured exit" and "actual failure".

## Files to modify

- `/Users/dev/yoke/.claude/skills/yoke/scripts/observe-tool.sh`

## Acceptance criteria

- [ ] Structured exits like approval waits are recorded distinctly from real failures.
- [ ] Session analysis can separate true tool errors from expected flow-control exits.
- [ ] The approval gate no longer inflates per-session failure counts.

## Ticket F

**Title:** Post-done-transition tool calls lose `item_id` attribution in the immediate post-done slice
**Project:** yoke | **Type:** issue | **Priority:** low

### Body

# Post-done-transition tool calls lose `item_id` attribution in the immediate post-done slice

## Problem

After YOK-1081 reached `done`, later tool calls in the same session no longer carried `item_id=1081` in the events table. This makes the post-done analysis slice look shorter and cleaner than it really was.

## Evidence (YOK-1081 session, 2026-03-20)

- `161` events were attributed to `item_id=1081`.
- The last attributed event in the immediate slice was at `2026-03-20T20:09:06.764Z`.
- The first unattributed post-done event in the immediate slice was at `2026-03-20T20:11:16.125Z`.
- There were `79` unattributed post-done events through `2026-03-20T20:17:00Z`.
- In the broader lifetime of the same session ID, there are `90` unattributed events total.

The immediate unattributed events include follow-up reads and queries that are obviously still about YOK-1081 and YOK-1061 investigation context.

## Root cause

The main-session attribution logic in `observe-tool.sh` only resolves item context from:

- the current-item marker, or
- a single active non-epic item fallback

Once the item is no longer active, the fallback cannot resolve it. That makes later same-session work fall into `anomaly_flags='unattributed'`.

## Files to modify

- `/Users/dev/yoke/.claude/skills/yoke/scripts/observe-tool.sh`

## Acceptance criteria

- [ ] Preserve item attribution through the done-transition and immediate post-done follow-up window.
- [ ] Add either a recently-completed fallback, an explicit item-id handoff, or another equivalent mechanism.
- [ ] Immediate post-done work should show up in per-item timelines instead of as unattributed noise.

## Ticket G

**Title:** Active sub-skill allows silent test command deviation and optimistic pass recording
**Project:** yoke | **Type:** issue | **Priority:** medium

### Body

# Active sub-skill allows silent test command deviation and optimistic pass recording

## Problem

The active sub-skill surfaces registered quick/full test commands, but it does not require the agent to either run them exactly, record a failing run, or record a waiver when part of the command fails for pre-existing reasons. The only explicit waiver guidance today is for E2E sensitivity, not for quick/full command failure.

## Evidence (YOK-1081 session, 2026-03-20)

Registered quick command:

```text
cd app && python3 -m pytest tests/ -k "not live" && cd web && npm run test
```

What happened:

1. The backend half failed with pydantic import errors.
2. The agent said:

```text
This is a pre-existing pydantic issue (YOK-1061 already tracked and resolved this). Not related to my changes. Let me run the frontend tests instead.
```

3. The agent ran only frontend unit tests after that.
4. `qa_run 1920` recorded a passing result for frontend tests.
5. The final recap later claimed:

```text
All 144 unit tests + 37 E2E tests passed
```

No failing backend QA run or waiver was recorded for the skipped part of the registered quick command.

## Root cause

`advance/implementing/SKILL.md` explicitly requires waivers for skipped E2E when a change is not E2E-sensitive, but it has no equivalent rule for quick/full command failures or partial substitution. That leaves room for silent deviation and optimistic pass recording.

## Files to modify

- `/Users/dev/yoke/.claude/skills/yoke/advance/implementing/SKILL.md`

## Acceptance criteria

- [ ] If a registered quick/full command fails, the agent must either fix it, record a failing QA run, or record an explicit waiver.
- [ ] Agents must not silently substitute a passing subset of the configured command and record a blanket pass.
- [ ] Final summaries must derive claims from recorded evidence and known waivers, not from optimistic narrative.

## Ticket H

**Title:** Browser screenshot artifact metadata stores the wrong route
**Project:** yoke | **Type:** issue | **Priority:** low

### Body

# Browser screenshot artifact metadata stores the wrong route

## Problem

Screenshot artifacts for YOK-1081 recorded `"route":"/"` in metadata, even though the actual scenarios targeted `/login` and `/forgot-password`.

## Evidence (YOK-1081 session, 2026-03-20)

- Requirement `1878` targeted `/login`.
- Requirement `1879` targeted `/forgot-password`.
- Artifact `139` metadata route was `/`.
- Artifact `140` metadata route was `/`.

## Root cause

The artifact writer is not preserving the scenario route when it persists screenshot metadata. It appears to fall back to `/`.

## Acceptance criteria

- [ ] Screenshot artifact metadata includes the actual route from the executed scenario.
- [ ] Multi-route scenarios no longer collapse metadata to `/`.
- [ ] Reviewers can identify which route a screenshot came from without opening the image.

## Ticket I

**Title:** Merge/done flow can skip project-specific runner detection
**Project:** yoke | **Type:** issue | **Priority:** low

### Body

# Merge/done flow can skip project-specific runner detection

## Problem

`merge-worktree.sh` only knows generic runner patterns like `npm test` and `make test`. That makes projects with explicit but non-generic runner commands look "untestable" at merge time.

## Evidence (YOK-1081 session, 2026-03-20)

- Merge output at `2026-03-20T19:59:25.659Z` included:

```text
Running tests...
(No test runner detected - skipping)
```

- The same session had already used project-specific commands such as `npm run test` and `npm run test:e2e`.
- `merge-worktree.sh` falls back to `(No test runner detected - skipping)` when neither generic branch matches.

## Root cause

The merge path does not consult the project command registry and only looks for generic test entry points.

## Files to modify

- `/Users/dev/yoke/.claude/skills/yoke/scripts/merge-worktree.sh`

## Acceptance criteria

- [ ] Merge-time test detection can use project-registered test commands when available.
- [ ] If merge-time verification is skipped, the operator sees exactly what project-specific verification was not attempted.
- [ ] External projects no longer appear runner-less solely because they use custom command names.

## Ticket J

**Title:** Agent execution hygiene papercuts in idea-to-done flows
**Project:** yoke | **Type:** issue | **Priority:** low

### Body

# Agent execution hygiene papercuts in idea-to-done flows

## Problem

Small avoidable tool-call issues still add noise to otherwise successful runs.

## Evidence (YOK-1081 session, 2026-03-20)

- At `2026-03-20T19:52:26.475Z`, a targeted edit failed with:

```text
String to replace not found in file.
String:     // Verify the "Back to the End Times" link is shown
```

- Exploration subagent `a2a143a458ee0eb6d` started with a broad `find` over the worktree and the first result batch was dominated by `node_modules/*.d.ts` paths.

## Root cause

Two separate papercuts showed up:

- follow-up edits do not gracefully no-op when a prior batch edit already changed the target
- discovery defaults are still broad enough to hit obvious noise like `node_modules`

## Acceptance criteria

- [ ] Source-discovery helpers exclude `node_modules` and similar noise directories by default.
- [ ] A stale targeted replace after a prior successful batch edit is reported as a benign no-op, not a hard-looking failure.
- [ ] Transcript noise from non-risky tool failures is reduced in successful idea-to-done flows.
