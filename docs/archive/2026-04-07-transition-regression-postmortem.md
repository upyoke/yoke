# Post-Mortem: Transition Name Regression (2026-04-07)

## Executive Summary

On 2026-04-07, the regression was not primarily "one bad rename plus one later cleanup." The larger system failure was that multiple long-running sessions were editing the shared `main` worktree at the same time.

Commit `e3d61a465` correctly introduced `planning_to_plan_drafted` as the shepherd transition name. A long-running Codex `/yoke polish` session (`019d697f-4703-7332-a75d-a86dea00e29a`) started essentially at the same moment on `main` to vet that commit. While it was still running, a separate Claude session (`ec7a1f69-adcf-422a-aacf-67751d3b7cd3`) made two commits on the same worktree: `d9b83fc50` added PRD-9, and `17085bd7c` removed the late AC gate but accidentally renamed `planning_to_plan_drafted` → `planning_to_planned` inside `boss-verdict.md`.

After `17085bd7c`, the Claude session explicitly reported that four shepherd-related files were still dirty from "the other session's shepherd work." The Codex session later resumed from the live dirty worktree, treated that mixed state as genuine transition drift, normalized 15 files to `planning_to_planned`, and committed `a51c2b03f`.

The biggest failure was shared mutable `main` with no per-session provenance, no worktree isolation, and no freshness protocol when another session changed the world underneath an active one. Secondary failures made the incident harder to catch and reconstruct: no required protected-surface verification after `17085bd7c`, no canonical lifecycle authority the propagating session was required to consult, and hook telemetry that was noisy but not authoritative or richly correlated enough to explain and stop the side effect in real time.

This revision corrects an earlier draft that misattributed `a51c2b03f` to session `019d68b9`. Archived ticket snapshots later in this file preserve the superseded draft language for historical record.

This post-mortem now documents the corrected transcript-backed timeline, the revised root cause analysis, the immediate fixes that landed, the superseded deleted ticket set for history, and the current improved plan.

---

## Timeline

| Time (ET) | Event |
|---|---|
| **Pre-incident** | Commit `e3d61a465` correctly establishes `planning_to_plan_drafted` as the intended shepherd transition name across the touched surfaces. |
| **15:50:42** | Codex session `019d697f-4703-7332-a75d-a86dea00e29a` starts as `/yoke polish` review work on shared `main`, explicitly vetting commit `e3d61a465`. Its startup "Recent commits" context stops at `e3d61a465`. |
| **16:02:09** | Claude session `ec7a1f69-adcf-422a-aacf-67751d3b7cd3` starts on the same shared `main` worktree to remove the late AC gate / assertion. |
| **16:07:36** | **Commit `d9b83fc50`** lands from the Claude session, adding PRD-9 AC validation to `prd-validate.sh`. The worktree is still dirty afterward. |
| **16:08:33** | **Commit `17085bd7c`** lands from the Claude session. It correctly removes the late AC gate, but accidentally rewrites `planning_to_plan_drafted` → `planning_to_planned` in `boss-verdict.md`, and the commit message itself uses the wrong transition name. |
| **16:08:34** | The same Claude session reports four remaining dirty files from "the other session's shepherd transition renames": `yoke-db.sh epic`, `test-prd-validate.sh`, `shepherd/SKILL.md`, and `design-and-plan.md`. At this point the shared worktree contains a mixture of committed and uncommitted changes from multiple sessions. |
| **16:08-16:18** | After context compaction, the long-running Codex session continues from the live dirty worktree. It treats the mixed shepherd state as remaining transition drift, updates doctor/tests/docs to align around `planning_to_planned`, reruns affected suites, and concludes the touched surface is now consistent. |
| **16:18:43** | The Codex session reports the affected suites green and says it finished "transition cleanup" across doctor/tests/docs. |
| **16:18:56** | User asks the Codex session to "commit all your changes from whole session." |
| **16:19:40** | **Commit `a51c2b03f`** lands from the Codex session, propagating `planning_to_planned` across 15 files. |
| **16:21:19** | The Codex session confirms that `a51c2b03f` is on `main`. |
| **18:04:32** | **Commit `6c32f705e`** restores `planning_to_plan_drafted` across the affected surfaces and removes the invalid `planning:planned` cascade mapping. |
| **Later investigation** | Transcript-level reconstruction shows that the earlier draft misattributed `a51c2b03f` to session `019d68b9`. The actual propagating session was `019d697f`, the long-running Codex polish session that overlapped the Claude edits on shared `main`. |

---

## Corrected Reconstruction

The most important corrected findings are:

1. **`a51c2b03f` was not created by session `019d68b9`.** It was created by the long-running Codex polish session `019d697f-4703-7332-a75d-a86dea00e29a`.
2. **The propagating session did not merely notice a committed inconsistency.** It absorbed another session's dirty shared-worktree state as live input.
3. **The later-commit hypothesis is only partly right.** The Codex session did begin before `d9b83fc50` and `17085bd7c`, but the deeper problem was not just stale startup context. The bigger problem was that both sessions edited the same mutable `main` worktree, so one session's dirty files became another session's perceived ground truth.
4. **The deny telemetry was real but underspecified.** The events DB records many `ToolCallDenied` rows for the Codex session, but those rows alone do not tell us which exact command each denial applied to or whether execution was actually prevented. The archived Codex transcript proves `git add` and `git commit` still executed.

---

## Root Cause Analysis

### Primary Systems Failure — Concurrent Sessions On Shared `main`

The dominant root cause was allowing multiple autonomous sessions to work directly in the same mutable `main` worktree.

The Codex polish session started on `main` at `15:50:42 ET` and remained active while the Claude session later committed `d9b83fc50` and `17085bd7c` to that same worktree. After the Claude work, four shepherd-related files were still dirty and explicitly identified as belonging to "the other session's shepherd work." There was no isolation boundary, no ownership marker on those dirty files, and no rule saying "stop, another session changed this surface under you."

This turned one session's local unfinished state into another session's input.

### Entry Point — Collateral Rename In `17085bd7c`

The immediate bug entry point was still the accidental rename in `17085bd7c`.

The Claude session was trying to remove the late AC gate and the related assertion. While editing nearby code in `boss-verdict.md`, it also changed `planning_to_plan_drafted` to `planning_to_planned` in several places. No lifecycle-aware validation stopped that edit, and the commit message itself repeated the wrong name.

So the incident still began with collateral damage from a focused edit. But that was only the entry point, not the full explanation for why the bad value spread.

### Propagation Mechanism — Live Dirty Worktree Treated As Authority

The Codex session propagated the regression because it reconciled against the live dirty worktree instead of an authoritative lifecycle source.

After context compaction, it continued from current file state and failing/affected suites, not from a freshly re-bootstrapped commit digest. In that state:

- `main` had already moved since the session began
- some relevant files were committed by another session
- other relevant files were still dirty from another session
- there was no provenance telling Codex which changes were its own and which belonged to another active session

Once it decided the repo had "transition drift," the system gave it no canonical place to ask "which name is actually correct?" The session then aligned doctor/tests/docs to the wrong local state and made that wrong state internally consistent.

### Containment Failure — Commit On `main` With Advisory Denials

The user explicitly told the Codex session to "commit all your changes from whole session," and the session did exactly that: it staged 15 files and created `a51c2b03f` on `main`.

The system should still have made that dangerous context visible and containable. It did not.

The events DB contains `154` `ToolCallDenied` rows for the Codex session, all from `lint-main-commit` / `impl_on_main`, including rows around the stage/commit window. But the archived transcript also shows `git add` and `git commit` succeeding. Because the denial events lack full causal correlation metadata, we cannot prove from the DB alone which denied tool call mapped to which executed command. Operationally, the deny signals were advisory, not authoritative.

### Detection Failure — No Protected-Surface Verification Or Cross-Session Warning

Nothing automatically forced the system to stop after `17085bd7c` or before `a51c2b03f`:

- **No protected-change verification gate** required shepherd/lifecycle suites to run after the risky AC-gate removal commit
- **No worktree provenance warning** said "these dirty files came from another active session"
- **No canonical transition authority** required the propagating session to verify lifecycle vocabulary before resolving drift
- **No cross-file transition validation** flagged `planning_to_planned` as an invalid shepherd transition name

The tests that would have caught the wrong name existed. They simply were not required at the moment they mattered most.

### Visibility Failure — Centralized Telemetry Was Uneven And Hard To Correlate

The Claude hook session had detailed raw transcript history, but Yoke's centralized events DB captured only session lifecycle events for it — no `ToolCallStarted`, `ToolCallCompleted`, or `ToolCallDenied` rows. The Codex session had many denial rows in the DB, but no corresponding started/completed rows and no top-level `tool_use_id` to tie the denials to the transcripted commands.

This meant the true sequence had to be reconstructed by combining:

- git history
- reflog
- raw Claude transcript
- raw Codex archived transcript
- partial events DB evidence

That is far too much archaeology for a failure mode that should have been obvious in real time.

---

## Six Systemic Gaps (Framed as "No Agent Error")

The "no agent error" principle still applies here, but the corrected framing is different. The core failure was not "one agent was careless and another agent copied it." The system invited multiple sessions to share mutable `main`, gave them no provenance model, and provided no authoritative conflict-resolution path.

1. **Shared mutable `main`** — Multiple long-running sessions could edit the same worktree concurrently.
2. **No provenance or freshness model** — A session could not tell whether dirty files were its own, another session's, or newly invalid because `main` had changed underneath it.
3. **No canonical lifecycle authority** — When files disagreed, there was no required source of truth for transition names.
4. **No protected-surface verification gate** — Shepherd/lifecycle changes were allowed to land without mandatory targeted verification.
5. **Advisory guardrails** — Hook denials were logged, but not reliably enforced or richly correlated to side effects.
6. **Wide propagation power** — Once a session decided it was "fixing drift," it could rewrite a large protected surface across scripts, tests, prompts, and docs in one pass.

---

## Immediate Fixes Applied

These fixes were already applied during the original incident-response work and remain correct after the revised reconstruction.

### 1. Restore the canonical transition name and status flow

**Commit `6c32f705e`** restored `planning_to_plan_drafted` across the affected surfaces and removed the invalid `planning:planned` cascade mapping from `yoke-db.sh epic`.

It also repaired YOK-1318 from `planned` back to `plan-drafted` via `repair-status.sh`.

### 2. Doctor HC gap fix

**Commit `dc8f29341`** updated `HC-shepherd-lifecycle` so epics at `plan-drafted` and `refining-plan` are also required to have the relevant shepherd verdict, rather than only checking `planned` and later states.

The corresponding lifecycle doctor tests were expanded and passed.

### 3. Regression verification of the restored state

Post-restore verification confirmed:

- all affected files were returned to `planning_to_plan_drafted`
- the invalid `planning:planned` cascade mapping was removed
- the affected shepherd/lifecycle suites passed
- zero stale `planning_to_planned` references remained in the restored surface

---

## Original Prevention Ticket Set (Later Deleted / Superseded)

Earlier in the night, an 8-ticket prevention set was filed from a first-pass reconstruction. Those issues were later deleted after we decided to rethink the ticketing from first principles.

That first-pass ticketing remains historically useful, but it was written before the transcript-level reconstruction corrected the propagation session attribution and elevated shared-`main` concurrency as the dominant systems failure. The detailed deleted ticket snapshots are preserved later in this file under **Archived Deleted Tickets (Pre-Deletion Snapshot)**. Use the corrected analysis above and the **Improved Plan** below as the current working view.

---

## Telemetry Evidence Summary

### Session `ec7a1f69-adcf-422a-aacf-67751d3b7cd3` (Originating Claude hook session)

- Harness offered: `2026-04-07T20:02:09Z` (`16:02:09 ET`)
- Harness ended: `2026-04-07T20:08:39Z` (`16:08:39 ET`)
- Centralized events DB: `7 SessionRegistered`, `7 SessionEnded`, `1 AgentSessionStarted`
- **No centralized ToolCall events** in Yoke's events DB
- Raw transcript proves it produced:
  - commit `d9b83fc50` at `16:07:36 ET`
  - commit `17085bd7c` at `16:08:33 ET`
- Raw transcript also proves it observed four remaining dirty files from "the other session's shepherd transition renames" immediately after `17085bd7c`

### Session `019d697f-4703-7332-a75d-a86dea00e29a` (Propagating Codex polish session)

- Session transcript start: `2026-04-07T19:50:42Z` (`15:50:42 ET`)
- Harness offered: `2026-04-07T19:51:14Z`
- Harness last heartbeat: `2026-04-07T20:21:38Z`
- Harness ended: `2026-04-07T20:43:47Z`
- Centralized events DB: `154 ToolCallDenied`, `4 SessionRegistered`, `3 SessionEnded`
- All observed denials in the DB are `lint-main-commit` / `impl_on_main`
- **No centralized ToolCallStarted/Completed rows** exist for the same session, so the DB alone cannot tell us which denied tool call maps to which side effect
- Raw archived Codex transcript proves it:
  - started as `/yoke polish` review of `e3d61a465`
  - later saw the shared worktree dirty with 15 shepherd/lifecycle/doc-related files eventually included in `a51c2b03f`
  - executed `git add` on those files
  - executed `git commit -m "fix shepherd transition drift and prd validation tests"`
  - produced commit `a51c2b03f` at `16:19:40 ET`

### What the telemetry now tells us

- The earlier attribution to session `019d68b9` was wrong
- The events DB alone was not sufficient to identify the real propagating session
- The raw harness transcripts were sufficient to reconstruct the actual sequence
- The combination of missing centralized tool telemetry for Claude hook sessions and under-correlated denial telemetry for Codex made the incident much harder to understand than it should have been

---

## Key Lessons

1. **Shared mutable `main` was the biggest problem.** One session's dirty state became another session's input.
2. **Provenance matters as much as protection.** The system needs to know who dirtied which files and whether `main` changed underneath an active session.
3. **Tests that don't run don't protect.** The relevant suites existed and would likely have caught the regression, but they were never required at the decisive moments.
4. **Hooks that don't block and don't correlate don't guard.** Denial rows without authoritative enforcement or causal linkage create false confidence.
5. **"Fix drift" is dangerous without authority.** If a session is allowed to reconcile inconsistency, it must have a canonical place to verify lifecycle vocabulary first.
6. **Collateral damage from focused edits is still the entry point.** The initial rename was accidental adjacent damage during a targeted gate-removal edit.
7. **There is no such thing as agent error.** The system incentives and surfaces made this failure easy to produce and hard to see.

---

## Improved Plan (Working Draft)

This section is a running draft of the revised ticket set we want to discuss. It supersedes the earlier prevention-ticket framing if we decide this newer structure is better.

### Draft ordering

1. Unified tool-call correlation and rich hook telemetry
2. Shared-main concurrency and provenance control
3. Canonical authority for lifecycle and scattered constants
4. Protected-change verification gate
5. Commit-boundary fidelity and containment
6. Protected-surface blast-radius and anomaly controls
7. Drift-resolution protocol and escalation rules

### Ticket A — Unified tool-call correlation and rich hook telemetry
**Status in discussion:** agreed priority
**Why first:** This does not replace enforcement, but it gives us the causal graph we currently lack. We should be able to answer: which exact tool call was attempted, what the hook saw, what denied it, what happened next, and whether the side effect still occurred.

**What it would do:**
- Make `tool_use_id` a first-class top-level field for every tool-call event shape across Claude Code and Codex
- Store the same correlation keys everywhere they exist: `session_id`, `tool_use_id`, `turn_id` when available, `tool_name`, and hook phase/source
- Persist richer structured payload data from hook events instead of collapsing everything into a tiny preview
- Ensure denial events, started events, completed events, failed events, and structured-exit events all participate in the same correlation model

**Implementation shape:**
- Add first-class event fields/columns for `tool_use_id`, `turn_id`, and hook phase/source
- Normalize extraction logic so Claude Code and Codex populate the same envelope shape, with nulls where a harness lacks a field
- Upgrade `emit-denial.sh` and all lint hooks to include correlation metadata and the relevant structured inputs they already have access to
- Capture truncated but structured `tool_input`, `tool_response`, and `error` data in a consistent `context.detail` layout
- Add event-query helpers and doctor checks that validate correlation coverage

**Key design rule:** store enough data to reconstruct the causal chain, but cap large payload fields and avoid unbounded raw transcript dumping by default

### Ticket B — Shared-main concurrency and provenance control
**Status in discussion:** draft
**Why this moved up:** The corrected reconstruction points to concurrent work on shared `main` as the dominant systems failure. One session's dirty files became another session's input, and neither session had a provenance model telling it that those files belonged to someone else.

**What it would do:**
- Make isolated worktrees / branches the default easy path for non-trivial sessions
- Treat shared `main` as an explicit, higher-risk operating mode rather than a casual convenience path
- Track provenance for dirty files and protected-surface edits so a session can see whether changes came from itself or another active / recent session
- Force a freshness check or re-anchor when protected surfaces change underneath a long-running session
- Warn or pause before staging / committing files dirtied by another session on shared `main`

**Implementation shape:**
- Add a lightweight session-aware provenance log or equivalent file-ownership metadata for protected surfaces
- Add shared-`main` leases / explicit override semantics so multiple sessions on `main` are a conscious choice
- Fingerprint the protected worktree at session start, resume, compaction, and pre-commit time to detect "the world changed under me"
- Surface "these files were last dirtied by session X" before a session stages or commits them
- Bias toward automatic branch / worktree handoff for longer-running implementation, polish, and repair work

**Key design rule:** the safe path has to be more convenient than bypassing the rule, or the operator will keep taking the risky path.

### Ticket C — Canonical authority for lifecycle and scattered constants
**Status in discussion:** draft
**Why this is foundational:** The propagation step happened because the system had no authoritative answer to "which name is correct?"

**What it would do:**
- Define one canonical source for lifecycle transitions and other scattered constants
- Generate derived surfaces from that source instead of hand-copying literals across docs, scripts, tests, and prompts
- Make drift resolution consult authority, not recency

**Implementation shape:**
- Start with shepherd lifecycle transitions as the first canonicalized surface
- Add generation or export steps for shell-facing consumers
- Add validation that derived surfaces match the canonical source
- Expand later to status names, event names, config keys, and session-mode labels

### Ticket D — Protected-change verification gate
**Status in discussion:** draft
**Why this matters:** Tests existed but were not required to run after `17085bd7c`, and nothing forced verification before the wider propagation commit landed.

**What it would do:**
- Require verification after changes to protected areas such as lifecycle, shepherd, hook, DB-wrapper, and routing surfaces
- Prefer a blunt, reliable first pass over a clever fully dynamic mapping system
- Fail the protected change path quickly when relevant verification fails

**Implementation shape:**
- Start with coarse path-to-suite mapping
- Run the whole relevant suite when protected files change
- Add a clear protected-change event trail so failures are visible in telemetry

**First-pass principle:** if lifecycle/shepherd files change, run the whole shepherd/lifecycle suite rather than waiting for perfect selective-test inference

### Ticket E — Commit-boundary fidelity and containment
**Status in discussion:** draft
**Why this moved down:** The commit boundary was the containment failure, not the origin failure. It still matters, but the corrected reconstruction suggests we should instrument and narrow this carefully instead of treating it as the first or only fix.

**What it would do:**
- Audit whether protected commit/stage denials are actually truthful about what happened
- Correlate deny / allow decisions with the real side effects at the git boundary
- Add a narrow git-level backstop for the specific invariant we can prove is both dangerous and repeatedly violated
- Turn repeated proven bypasses into a containment / escalation event, not just a logged annoyance

**Implementation shape:**
- Run in shadow / fidelity-audit mode first so we can see the actual mismatch between hook outcome and git side effect
- Start with commit and stage on protected surfaces rather than trying to solve every protected write at once
- Keep the backstop narrow and evidence-driven
- Treat any stronger "session fuse" behavior as follow-on hardening after the causal data is in place

**Important nuance:** this ticket is now about truthful containment, not broad speculative lockdown.

### Ticket F — Protected-surface blast-radius and anomaly controls
**Status in discussion:** draft
**Why this matters:** Once a session crosses into a protected domain, we need the system to notice wide rewrites, suspicious reversals of recent work, and deny-to-side-effect mismatches as first-class anomalies.

**What it would do:**
- Add protected-path and change-count circuit breakers for wide edits on sensitive surfaces
- Detect suspicious reversals of recent intentional work
- Detect when a denied tool call is followed by the protected side effect anyway
- Surface these as high-severity anomalies instead of leaving them to post-hoc archaeology

**Implementation shape:**
- Define protected file classes and blast-radius thresholds for lifecycle / shepherd / hook / DB-wrapper surfaces
- Correlate deny events with subsequent commits, writes, status mutations, or branch changes
- Add a specific anomaly/event for deny-bypassed side effects
- Add revert/anomaly detection on top of the correlation substrate, especially for recent intentional values being rewritten back to stale ones

**Note:** this is where revert detection belongs conceptually for me — as part of anomaly correlation on protected surfaces, not as an isolated first-ticket guardrail.

### Ticket G — Drift-resolution protocol and escalation rules
**Status in discussion:** draft
**Why this matters:** Once the system sees inconsistency, it needs a reliable rule for what to do next instead of "pick the newest file."

**What it would do:**
- Require canonical-source lookup before resolving cross-file drift in protected domains
- Define when the agent may auto-align files and when it must stop and escalate
- Teach prompts, skills, and docs the same protocol

**Implementation shape:**
- Create a canonical-source map for major value categories
- Add explicit "stop and verify" rules for lifecycle, routing, event, and status vocabulary
- Treat unresolved protected-domain inconsistency as an escalation condition, not a cleanup opportunity

### Working notes

- Ticket A is the one already explicitly supported and should be treated as the current first draft priority.
- The corrected reconstruction moves shared-`main` concurrency / provenance control much higher than the earlier draft did.
- Commit-boundary work still matters, but it now reads as containment hardening rather than the primary root-cause fix.
- Transition-specific lint and doctor checks are still useful, but they should fall out of Tickets C and D rather than lead the strategy.
- The archived deleted tickets below intentionally preserve the earlier framing; they are historical snapshots, not the current recommendation.

### Archived Deleted Tickets (Pre-Deletion Snapshot)

The following archive captures the local Yoke items and GitHub issues that were filed from the original prevention-ticket set before deletion. At deletion time, the local item bodies matched the GitHub issue bodies verbatim.

These archived bodies intentionally preserve the earlier draft framing, including the now-superseded session attribution and earlier ticket ordering. They are retained for historical completeness, not as the current recommendation.

| Local item | GitHub issue | Local status | Priority | Created at | Updated at |
|---|---|---|---|---|---|
| `YOK-1322` | `#3212` | `idea` | `high` | `2026-04-07T22:55:14Z` | `2026-04-07T22:55:57Z` |
| `YOK-1323` | `#3213` | `idea` | `high` | `2026-04-07T22:56:15Z` | `2026-04-07T22:56:46Z` |
| `YOK-1324` | `#3214` | `idea` | `high` | `2026-04-07T22:56:54Z` | `2026-04-07T23:14:39Z` |
| `YOK-1325` | `#3215` | `idea` | `high` | `2026-04-07T22:57:31Z` | `2026-04-07T23:13:57Z` |
| `YOK-1326` | `#3216` | `idea` | `medium` | `2026-04-07T22:58:21Z` | `2026-04-07T23:15:12Z` |
| `YOK-1327` | `#3217` | `idea` | `high` | `2026-04-07T23:10:43Z` | `2026-04-07T23:11:17Z` |
| `YOK-1328` | `#3218` | `idea` | `high` | `2026-04-07T23:11:27Z` | `2026-04-07T23:12:03Z` |
| `YOK-1329` | `#3219` | `idea` | `high` | `2026-04-07T23:12:19Z` | `2026-04-07T23:12:57Z` |

**Local metadata shared by all archived items:**
- `project=yoke`
- `deployment_flow=yoke-internal`
- `source=ben`
- `labels=type:issue,status:idea,source:ben,+priority label`

**Dependency edges present at deletion time:**
- `YOK-1322` depended on `YOK-1324` (`activation`, `status:done`) — "Lint hook validates against the canonical transition registry"
- `YOK-1323` depended on `YOK-1324` (`activation`, `status:done`) — "Doctor HC validates against the canonical transition registry"

#### `YOK-1322` / `#3212`

- Local title: `Lint hook: validate shepherd transition names against lifecycle.py canonical source`
- GitHub URL: <https://github.com/upyoke/yoke/issues/3212>
- GitHub labels: `type:issue`, `priority:high`, `status:idea`, `source:ben`

```md
# Lint hook: validate shepherd transition names against lifecycle.py canonical source

## Problem

Shepherd transition names (e.g., `planning_to_plan_drafted`, `refined_idea_to_planning`) exist as raw string literals scattered across 14+ files — shepherd SKILL.md, boss-verdict.md, design-and-plan.md, doctor.sh, yoke-db.sh epic, tests, docs, agent definitions. No automated check validates these strings correspond to real lifecycle transitions defined in `yoke/api/domain/lifecycle.py`.

When one file introduces an invalid transition name, no hook blocks it. Subsequent "drift fix" sessions then propagate the error across all files.

## Incident Evidence

**Commit `17085bd7c`** (Claude Opus 4.6, session `ac4fd3fc`, 2026-04-07 16:08): Edited boss-verdict.md to remove an AC gate assertion. While editing, renamed `planning_to_plan_drafted` → `planning_to_planned` in 4+ places. No hook blocked the invalid transition name.

**Commit `a51c2b03f`** (GPT-5.4/Codex, session `019d68b9`, 2026-04-07 16:19): Saw the inconsistency, "fixed drift" by aligning 14 more files to the wrong version. `lint-main-commit` fired 64 `ToolCallDenied` events (`impl_on_main` check) — but had no concept of transition name validity.

**Fix commit `6c32f705e`**: Restored `planning_to_plan_drafted` across all 14 files.

## Proposed Solution

A `PreToolUse/Bash` + `PreToolUse/Write` lint hook (`lint-transition-names.sh`) that:

1. Extracts transition name patterns from the tool input (patterns: `\w+_to_\w+` appearing in shepherd/lifecycle context)
2. Derives valid transition names from `lifecycle.py` (adjacent status pairs in `EPIC_PROGRESSION` and `ISSUE_PROGRESSION`)
3. Blocks the edit/write if an unrecognized transition name is introduced
4. Bypass: `# lint:no-transition-check`

**Source of truth:** `yoke/api/domain/lifecycle.py` defines `EPIC_PROGRESSION` and `ISSUE_PROGRESSION`. Valid transition names are derivable from adjacent status pairs (e.g., `planning` → `plan-drafted` = `planning_to_plan_drafted`, with hyphens converted to underscores).

**Scope:** Only check files under `.agents/skills/yoke/shepherd/`, `.agents/skills/yoke/scripts/doctor.sh`, `.agents/skills/yoke/scripts/yoke-db.sh epic`, `.claude/agents/yoke-boss.md`, and `yoke/docs/`.

## Acceptance Criteria

- [ ] AC-lint-transition-new-hook: `lint-transition-names.sh` exists and is wired into settings.json PreToolUse hooks
- [ ] AC-lint-transition-valid-pass: Valid transition names like `planning_to_plan_drafted` pass the check silently
- [ ] AC-lint-transition-invalid-block: Invalid transition names like `planning_to_planned` are blocked with a clear error message showing the valid alternatives
- [ ] AC-lint-transition-bypass: `# lint:no-transition-check` suppresses the check
- [ ] AC-lint-transition-lifecycle-source: Validation derives valid names from lifecycle.py, not a hardcoded list
- [ ] AC-lint-transition-tests: Test suite covers valid, invalid, bypass, and edge cases
```

#### `YOK-1323` / `#3213`

- Local title: `Doctor HC: detect transition name drift between shepherd files and lifecycle.py`
- GitHub URL: <https://github.com/upyoke/yoke/issues/3213>
- GitHub labels: `type:issue`, `priority:high`, `status:idea`, `source:ben`

```md
# Doctor HC: detect transition name drift between shepherd files and lifecycle.py

## Problem

When transition names drift in one file, there's no health check that detects the inconsistency until a shepherd run fails at runtime. The doctor already has HC-shepherd-lifecycle, but it only checks that verdicts exist for items at certain statuses — it does NOT check that transition names referenced in shepherd skill files, doctor.sh, yoke-db.sh epic, or agent definitions are valid or consistent with each other.

## Incident Evidence

**Commit `17085bd7c`** (2026-04-07 16:08): Changed `planning_to_plan_drafted` → `planning_to_planned` in boss-verdict.md. For 11 minutes, boss-verdict.md said `planning_to_planned` while SKILL.md said `planning_to_plan_drafted`. No doctor HC would have flagged this inter-file inconsistency.

**Commit `a51c2b03f`** (2026-04-07 16:19): "Resolved" the inconsistency by aligning 14 files to the wrong version. A doctor HC that compared all shepherd file transition references against lifecycle.py would have flagged every file as containing an invalid transition name.

## Proposed Solution

**HC-transition-name-consistency:**

1. Extract all transition name strings from:
   - `.agents/skills/yoke/shepherd/*.md`
   - `.agents/skills/yoke/scripts/doctor.sh` (verdict SQL queries)
   - `.agents/skills/yoke/scripts/yoke-db.sh epic` (cascade mappings)
   - `.claude/agents/yoke-boss.md`
   - `yoke/docs/` (reference docs)

2. Derive valid transition names from `lifecycle.py` EPIC_PROGRESSION and ISSUE_PROGRESSION adjacent status pairs

3. Flag any transition name that doesn't match a valid derivation

4. Flag inconsistencies between files (file A uses name X, file B uses name Y for the same source→target pair)

**Also fix:** HC-shepherd-lifecycle (doctor.sh line 2831 before YOK-1322 fix) should include `plan-drafted` and `refining-plan` in the status check list — items at those statuses must also have the `planning_to_plan_drafted` verdict. **UPDATE: This sub-fix was already applied in the current session** (doctor.sh updated, 2 new tests added, 12/12 passing). This ticket covers the broader HC for transition name consistency across files.

## Acceptance Criteria

- [ ] AC-hc-transition-consistency: New HC check `HC-transition-name-consistency` exists in doctor.sh
- [ ] AC-hc-extract-transitions: HC extracts transition names from all relevant files (shepherd/*.md, doctor.sh, yoke-db.sh epic, yoke-boss.md)
- [ ] AC-hc-validate-against-lifecycle: HC validates extracted names against lifecycle.py-derived valid transition names
- [ ] AC-hc-cross-file-drift: HC detects when two files use different transition names for the same lifecycle step
- [ ] AC-hc-warn-severity: Issues reported as WARN severity (consistent with HC-shepherd-lifecycle)
- [ ] AC-hc-tests: Test suite covers valid state, single-file invalid, cross-file inconsistency
```

#### `YOK-1324` / `#3214`

- Local title: `Canonicalize shepherd transition names in a single registry module`
- GitHub URL: <https://github.com/upyoke/yoke/issues/3214>
- GitHub labels: `type:issue`, `priority:high`, `status:idea`, `source:ben`

```md
# Canonical source registry: eliminate string-literal scatter across codebase

## Problem — broadened from original scope

Originally scoped to shepherd transition names. The real problem is general: **any value that exists as a raw string literal in multiple files can silently drift.** Transition names are one instance. The same anti-pattern exists for:

- **Transition names** (`planning_to_plan_drafted` in 14+ files)
- **Status names** (`plan-drafted`, `refining-plan` referenced in skill files, doctor.sh, yoke-db.sh epic, tests)
- **Event names** (`ToolCallDenied`, `ItemStatusChanged` scattered across emit-event.sh callers)
- **Column names** (referenced in raw SQL across scripts — partially mitigated by lint-sqlite-cmd.sh column check, but only for known tables)
- **Config keys** (`wip_cap`, `default_project`, `frontier_since` in config + board renderer + docs)
- **Session modes** (`hook`, `refine`, `charge` in harness scripts + session-start + routing logic)

When Session A introduces a typo or old name in one file, Session B sees "inconsistency" and propagates the wrong version. Without a canonical source, "which file is right?" is unanswerable.

## Incident Evidence

Commit `e3d61a465` correctly introduced `planning_to_plan_drafted` as the transition name. Commit `17085bd7c` accidentally reverted it to `planning_to_planned` in one file. Commit `a51c2b03f` then propagated the wrong name to 14 files. If a canonical registry existed, the propagating session would have known immediately which name was correct.

## Proposed Solution

### 1. Transition registry in lifecycle.py

Add `SHEPHERD_TRANSITIONS` dict mapping transition names to (from_status, to_status, owner_skill, worker) metadata. Derive from `EPIC_PROGRESSION` and `ISSUE_PROGRESSION` adjacent pairs so names stay in sync with progressions.

### 2. Shell-consumable exports

Like `lifecycle_export.py` → `status-lifecycle.sh`, generate shell-consumable registry files:
- `transition-registry.sh` — valid transition names
- `config-keys.sh` — valid config keys with descriptions
- `session-modes.sh` — valid session modes

### 3. General pattern: canonical source → generated validators

Establish a pattern where:
1. Canonical source defines the valid values (Python module, DB table, config file)
2. Export script generates shell-consumable validators
3. Lint hooks validate references against the exported validators
4. Doctor HCs detect cross-file drift

This pattern should be documented and reusable for any new category of scattered constants.

### 4. Parity tests

For each canonical source, a test verifies that all references in skill files, scripts, docs, and agent definitions match the canonical values. These tests serve as a safety net even if the lint hooks are bypassed.

## Dependencies

YOK-1322 (lint hook for transition names) and YOK-1323 (doctor HC for transition drift) are specific implementations that would use this registry. This ticket provides the foundation.

## Acceptance Criteria

- [ ] AC-canonical-transition-registry: `SHEPHERD_TRANSITIONS` dict exists in lifecycle.py mapping names to from/to/owner/worker
- [ ] AC-canonical-derived: Transition names derived from progression adjacent pairs, not hardcoded independently
- [ ] AC-canonical-shell-export: Shell-consumable export for transition names (transition-registry.sh)
- [ ] AC-canonical-parity-tests: Tests verify all references in shepherd/*.md, doctor.sh, yoke-db.sh epic match the registry
- [ ] AC-canonical-pattern-doc: Documentation describes the general "canonical source → export → validate" pattern for future categories
- [ ] AC-canonical-extensible: Pattern is demonstrated for at least one non-transition category (e.g., config keys or session modes)
```

#### `YOK-1325` / `#3215`

- Local title: `Codex hook denial enforcement gap: 64 denials did not block commit`
- GitHub URL: <https://github.com/upyoke/yoke/issues/3215>
- GitHub labels: `type:issue`, `priority:high`, `status:idea`, `source:ben`

```md
# Hook enforcement parity: all harnesses must enforce denials or hooks are worthless

## Problem — broadened from original scope

This ticket was originally scoped to Codex hook denial enforcement. The real problem is broader: **if ANY harness ignores hook denials, every hook-based guardrail in the system is unreliable.** The entire hook architecture assumes denials block the action. When they don't, hooks become telemetry-only — they record that something bad happened but don't prevent it.

This affects every current and future hook:
- `lint-main-commit.sh` — implementation code on main
- `lint-sqlite-cmd.sh` — direct sqlite access, column validation, lifecycle mutations
- `lint-event-registry.sh` — unregistered event names
- `lint-write-path.sh` — dangerous write paths
- `lint-test-pipe.sh` — test output piped to tail/head
- `lint-tc-label.sh` — sequential test case labels
- Any future hook added by YOK-1327 (post-commit regression gate), YOK-1328 (revert detection), or YOK-1329 (scope enforcement)

If Codex doesn't enforce denials, none of these hooks protect against Codex sessions. That's not a Codex-specific problem — it's a system integrity problem.

## Telemetry Evidence

Session `019d68b9` (GPT-5.4/Codex, mode=refine, 2026-04-07 16:14-16:24):
- `lint-main-commit.sh` fired 64 times with `impl_on_main` denial
- Denials spanned the entire session: 16:15:08 to 16:23:57
- Commit `a51c2b03f` landed at 16:19:40 despite the denials
- The commit touched 15 files including doctor.sh, yoke-db.sh epic, 8 test suites, SKILL.md, and agent definitions — clearly implementation code, clearly on main

## Secondary Issue: Telemetry Blind Spot

Session `ac4fd3fc` (Claude Opus, mode=hook, 2026-04-07 15:52-16:14):
- ZERO ToolCall telemetry events — observe-tool.sh not active for this mode
- Committed `17085bd7c` changing shepherd skill files on main
- We have no visibility into whether lint-main-commit fired, was denied, or was bypassed
- **Telemetry blind spot:** sessions without observe-tool.sh can make arbitrary changes with no audit trail

## Investigation Needed

1. **How does Codex handle PreToolUse hook denials?** Does `.codex/hooks.json` support the same deny semantics as Claude Code's `.claude/settings.json`? Is there a schema difference?
2. **Did the session bypass the hook?** Check if the commit command included `# lint:no-main-check`.
3. **Is this a known Codex limitation?** Check Codex docs for hook enforcement behavior.
4. **Should observe-tool.sh run on ALL sessions?** The telemetry blind spot for hook-mode sessions means regressions can be introduced without any tool-call audit trail.

## Proposed Solutions

### 1. Audit all harnesses for denial enforcement
- Claude Code: verify PreToolUse denial semantics actually block tool execution
- Codex: investigate `.codex/hooks.json` denial behavior — does it support blocking? If not, what alternatives exist?
- Any future harness: document denial enforcement requirements in `yoke/docs/harness-adapter-template.md`

### 2. Defense-in-depth via git hooks
- Implement critical guards as `.git/hooks/pre-commit` in addition to CLI hooks
- Git pre-commit hooks run in git itself, independent of any AI tool's hook system
- This is the only defense layer that works regardless of harness

### 3. Extend observe-tool.sh to all session modes
- Currently only runs on 6 worker agents
- ALL session modes (hook, refine, charge, wait, etc.) need tool-call telemetry
- No session should be able to modify files without an audit trail

### 4. Hook enforcement health check
- Doctor HC that verifies hooks are correctly configured and enforced
- Test: make a deliberate bad action, verify the hook blocks it, verify the telemetry records the denial
- Run periodically, not just on demand

## Acceptance Criteria

- [ ] AC-hook-parity-audit: All harnesses (Claude Code, Codex, any future) audited for denial enforcement
- [ ] AC-hook-git-defense: Critical guards (impl-on-main at minimum) implemented as `.git/hooks/pre-commit`
- [ ] AC-hook-telemetry-all-modes: observe-tool.sh (or equivalent) active on ALL session modes, not just worker agents
- [ ] AC-hook-parity-doc: `yoke/docs/hook-parity-map.md` documents enforcement behavior per harness
- [ ] AC-hook-enforcement-hc: Doctor HC verifies hooks are configured and enforced
```

#### `YOK-1326` / `#3216`

- Local title: `Drift-fix protocol: require canonical source verification before aligning files`
- GitHub URL: <https://github.com/upyoke/yoke/issues/3216>
- GitHub labels: `type:issue`, `priority:medium`, `status:idea`, `source:ben`

```md
# Drift-fix protocol: require canonical source verification before aligning files

## Problem — broadened from original scope

When a session detects inconsistencies between files, it "fixes drift" by aligning all files to one version. If the anchor file is wrong, the fix propagates the regression. This is a general anti-pattern — not specific to transition names.

The same failure mode applies to:
- Status names in skill files vs lifecycle.py
- Column names in SQL queries vs actual schema
- Event names in emit-event.sh calls vs event_registry
- Config key references vs yoke/config
- Any value that appears in multiple files

There is no documented protocol, no agent instruction, and no automated check that says "before resolving an inconsistency, verify which version is correct against the canonical source."

## Incident Evidence

GPT-5.4/Codex session `019d68b9` (mode=refine, 2026-04-07) detected inconsistency between boss-verdict.md (`planning_to_planned`) and SKILL.md (`planning_to_plan_drafted`). It chose to align to boss-verdict.md — the most recently modified file. Commit message: "fix shepherd transition drift and prd validation tests."

If the session had checked `lifecycle.py` (the canonical source for statuses), it would have found `plan-drafted` in `EPIC_PROGRESSION` and aligned the other direction. But nothing told it to check lifecycle.py. No agent instruction, no session rule, no CLAUDE.md directive mentions canonical source verification.

## Proposed Solution

### 1. Canonical source verification protocol in session rules

Add to `.claude/rules/session.md`:

```markdown
## Canonical Source Verification
When you detect naming or value inconsistencies between files:
1. NEVER assume the most-recently-modified file is correct
2. ALWAYS identify and check the canonical source:
   - Status/transition names → lifecycle.py (EPIC_PROGRESSION, ISSUE_PROGRESSION)
   - Column names → PRAGMA table_info or db-reference.md
   - Event names → event_registry table
   - Config keys → yoke/config
   - Hook names → settings.json
3. Align TO the canonical source, not to the most-recently-modified file
4. If no canonical source exists, ASK the user rather than guessing
5. If the canonical source itself seems wrong, flag it — don't silently propagate
```

### 2. Add verification awareness to ALL agent prompts

Not just Architect/Engineer/Boss — every agent that can edit files needs this:

```markdown
**Canonical source verification:** When you detect naming inconsistencies between files, 
verify against the canonical source before aligning. See session rules for the source map.
```

### 3. Drift-fix detection in lint hooks

A PreToolUse hook that detects "drift fix" patterns — edits that change a value in multiple files to match a single anchor. When detected, inject a reminder: "You are aligning {N} files to match {anchor}. Have you verified {anchor} is correct against the canonical source?"

### 4. Canonical source map in docs

Create `yoke/docs/canonical-sources.md` listing every category of scattered value, its canonical source, and how to verify. This is the reference that agents and operators consult.

## Acceptance Criteria

- [ ] AC-drift-protocol-session: Session rules include canonical source verification protocol with source map
- [ ] AC-drift-protocol-agents: ALL agent definitions (not just 3) include drift-fix awareness
- [ ] AC-drift-protocol-canonical-map: `yoke/docs/canonical-sources.md` exists with complete source map
- [ ] AC-drift-protocol-lint-reminder: Lint hook detects multi-file alignment patterns and reminds about canonical verification
```

#### `YOK-1327` / `#3217`

- Local title: `Post-commit regression gate: auto-run affected tests after every main commit`
- GitHub URL: <https://github.com/upyoke/yoke/issues/3217>
- GitHub labels: `type:issue`, `priority:high`, `status:idea`, `source:ben`

```md
# Post-commit regression gate: auto-run affected tests after every main commit

## Problem

When a session commits to main, nothing validates that the commit didn't break existing functionality. Tests exist but only run when someone thinks to run them. This means regressions can persist for hours or days — and worse, subsequent sessions can propagate the regression further before anyone notices.

This is the single highest-leverage gap in the system. Every other guardrail becomes less critical if regressions are caught within seconds of introduction.

## Incident Evidence

**Commit `17085bd7c`** (2026-04-07 16:08) renamed `planning_to_plan_drafted` → `planning_to_planned` in boss-verdict.md. The test suite `test-shepherd-state.sh` checks for `planning_to_plan_drafted` and would have FAILED immediately. But no test ran. 11 minutes later, session `019d68b9` propagated the error to 14 more files (commit `a51c2b03f`). If tests had run after `17085bd7c`, the regression would have been caught before it could spread.

This pattern applies to ANY regression, not just transition names — reverted bug fixes, deleted tests, broken function signatures, corrupted configurations.

## Proposed Solution

A `PostToolUse/Bash` hook that triggers after `git commit` commands on main:

1. **Identify affected test suites** from the committed files:
   - Changes to `shepherd/*.md` → run `test-shepherd-state.sh`, `test-shepherd-log.sh`, `test-caveats-merge.sh`
   - Changes to `doctor.sh` → run `test-doctor-hc-*.sh`
   - Changes to `yoke-db.sh epic` → run `test-yoke-db.sh epic`
   - Changes to `yoke-db.sh` → run `test-yoke-db.sh`
   - Changes to any script → run its corresponding test if one exists (convention: `scripts/foo.sh` → `scripts/tests/test-foo.sh`)

2. **Run affected tests** (not the full suite — keep it fast)

3. **On failure:** Emit a FATAL-severity event (`PostCommitRegressionDetected`) and inject a hard-stop message into the session: "REGRESSION DETECTED: {test} failed after your commit. Fix before proceeding."

4. **On success:** Emit an INFO event (`PostCommitTestsPassed`) and proceed silently

### Design considerations

- **Speed:** Only run affected tests, not the full suite. Map changed files to test suites via a static mapping or naming convention.
- **Scope:** Only trigger on main branch commits. Worktree commits have their own test discipline.
- **False positives:** If a test was already failing before the commit, don't blame this commit. Compare against a known-good baseline or check if the failure is new.
- **Harness parity:** Must work on both Claude Code and Codex. If implemented as a PostToolUse hook, verify enforcement on both platforms. Consider also implementing as a git post-commit hook for defense-in-depth.

## Acceptance Criteria

- [ ] AC-post-commit-gate: After every `git commit` on main, affected test suites run automatically
- [ ] AC-post-commit-mapping: Changed files map to relevant test suites (static mapping or convention-based discovery)
- [ ] AC-post-commit-hard-stop: Test failures produce a FATAL event and hard-stop message preventing further work
- [ ] AC-post-commit-silent-pass: Test successes proceed silently with an INFO event
- [ ] AC-post-commit-speed: Only affected tests run (not the full suite), keeping the gate under 30 seconds
- [ ] AC-post-commit-harness-parity: Works on both Claude Code and Codex (or defense-in-depth via git hook)
```

#### `YOK-1328` / `#3218`

- Local title: `Revert detection hook: flag commits that undo recent intentional changes`
- GitHub URL: <https://github.com/upyoke/yoke/issues/3218>
- GitHub labels: `type:issue`, `priority:high`, `status:idea`, `source:ben`

```md
# Revert detection hook: flag commits that undo recent intentional changes

## Problem

The system has zero awareness of recent change provenance. A session can commit changes that directly undo work from a commit made minutes ago, and nothing flags this. The current lint hooks check file categories (bookkeeping vs implementation) and SQL syntax — they have no concept of "this change reverses what was just done."

This is how regressions propagate: Session A makes a correct change. Session B doesn't understand it, sees "inconsistency," and reverts it — often across many more files than Session A touched.

## Incident Evidence

**Commit `17085bd7c`** (16:08) changed `planning_to_plan_drafted` → `planning_to_planned` in boss-verdict.md. This was itself an accidental revert of commit `e3d61a465` which had correctly introduced `planning_to_plan_drafted` as the new transition name. No hook detected that `17085bd7c` was undoing recent intentional work.

**Commit `a51c2b03f`** (16:19) then changed `planning_to_plan_drafted` → `planning_to_planned` in 14 MORE files — directly reverting the correct values that had been in place since `e3d61a465`. Each of these changes undid a specific line from a recent commit. A revert-detection hook would have flagged every one.

This pattern is general:
- A session "cleaning up" code reverts a bug fix it doesn't understand
- A session resolving merge conflicts takes the wrong side
- A session "fixing drift" aligns to the wrong anchor
- A session refactoring deletes a test added for a specific regression

## Proposed Solution

A `PreToolUse/Bash` hook on `git commit` that:

1. **Computes the proposed diff** from staged changes
2. **Compares against recent commits** (last N commits on main, configurable, default 20)
3. **Detects revert patterns:**
   - Line removed that was added in a recent commit
   - Line changed FROM the value introduced in a recent commit TO a different value
   - File deleted that was created in a recent commit
4. **Flags with context:** "WARNING: This commit reverts changes from {commit_hash} ({commit_message}, {time_ago}). Lines affected: {count}. Proceed? (The session should verify this is intentional.)"
5. **Threshold-based:** Small overlaps (1-2 lines) are common in legitimate edits. Flag when the revert ratio exceeds a threshold (e.g., >30% of the diff consists of reversals of recent work).

### Design considerations

- **Performance:** Comparing against 20 recent commits on every commit could be slow. Cache recent diffs or use git's built-in diff machinery efficiently.
- **False positives:** Legitimate reverts exist (rollbacks, cherry-pick conflicts). The hook should flag, not hard-block. Use WARN severity with a bypass.
- **Scope:** Only check main branch. Worktree branches have their own discipline.
- **Granularity:** Line-level comparison, not just file-level. A file being modified isn't suspicious; specific lines being changed back IS.

## Acceptance Criteria

- [ ] AC-revert-detect-hook: PreToolUse/Bash hook exists and fires on `git commit` on main
- [ ] AC-revert-detect-recent: Compares staged changes against last N commits (configurable)
- [ ] AC-revert-detect-line-level: Detects line-level reversals (value changed FROM recent-commit-value TO something else)
- [ ] AC-revert-detect-context: Warning message includes the commit hash, message, and time of the reverted work
- [ ] AC-revert-detect-threshold: Only flags when revert ratio exceeds configurable threshold
- [ ] AC-revert-detect-bypass: Bypass available for intentional reverts
- [ ] AC-revert-detect-tests: Test suite covers revert detection, threshold, bypass, and false-positive scenarios
```

#### `YOK-1329` / `#3219`

- Local title: `Session scope enforcement: limit blast radius by mode and change count`
- GitHub URL: <https://github.com/upyoke/yoke/issues/3219>
- GitHub labels: `type:issue`, `priority:high`, `status:idea`, `source:ben`

```md
# Session scope enforcement: limit blast radius by mode and change count

## Problem

Every session mode (hook, refine, charge, conduct, usher, etc.) has an implicit scope — what it's supposed to touch. But nothing enforces these boundaries. A "refine" session can rewrite tests, scripts, agent definitions, and docs in a single commit. A "hook" session can rename core lifecycle constants. The blast radius of any session is unlimited.

This is how small errors become large ones. The originating error in the transition regression was 4 changed lines in one file. The propagation was 15 files and 389 changed lines — because the propagating session had no scope limits.

## Incident Evidence

**Session `019d68b9`** (GPT-5.4, mode=refine, 2026-04-07):
- Modified 15 files: doctor.sh, yoke-db.sh epic, 8 test suites, SKILL.md, design-and-plan.md, yoke-boss.md, 3 docs
- This is not "refinement" — it's a system-wide rewrite
- A scope limit of "refine mode can only touch the item's own artifacts" would have blocked this entirely

**Session `ac4fd3fc`** (Opus, mode=hook):
- Modified boss-verdict.md and planning-to-planned-gates.md
- The task was removing an AC gate — a focused change to specific sections
- Accidentally changed transition names in adjacent lines — collateral damage from unbounded editing scope

## Proposed Solution

### 1. Mode-based file scope limits

Define allowlists per session mode. Enforce via PreToolUse hooks on Edit/Write/Bash(git commit):

| Mode | Allowed file patterns | Max files per commit |
|---|---|---|
| `hook` | Config files, settings, hook scripts | 5 |
| `refine` | The item's own skill/artifact files, docs | 8 |
| `charge` | Worktree files (never main) | unlimited |
| `conduct` | Worktree files (never main) | unlimited |
| `polish` | Existing worktree files only | unlimited |
| `usher` | Merge/deploy scripts, board, backlog views | 10 |

### 2. Change-count circuit breaker

If a session's staged diff touches more than N files (configurable, default 10) in a single commit on main, pause with a WARNING:

"This commit modifies {N} files. Session mode '{mode}' typically touches {expected}. Review the diff before proceeding."

### 3. Collateral damage detection

When a session edits a file, compare the edit scope against the stated task. If the edit changes lines outside the targeted section (e.g., changing transition names when the task is "remove AC gate"), flag the non-task-related changes.

This is harder to implement than scope limits but addresses the root cause of Session A's error — it wasn't trying to rename transitions, it just accidentally did while editing nearby code.

## Design Considerations

- **Session mode is already tracked** in `harness_sessions.mode` — the enforcement layer can read it
- **Bypass:** `# lint:no-scope-check` for legitimate cross-cutting changes
- **Incremental:** Start with the change-count circuit breaker (simplest, highest impact), then add mode-based file scoping
- **Worktree exemption:** Sessions working in worktrees (conduct, charge) already have isolation — scope limits matter most for main-branch work

## Acceptance Criteria

- [ ] AC-scope-circuit-breaker: Commits on main touching more than N files (configurable) produce a WARNING with file count and mode context
- [ ] AC-scope-mode-limits: At least 3 session modes (hook, refine, usher) have file-pattern allowlists enforced via PreToolUse hook
- [ ] AC-scope-bypass: `# lint:no-scope-check` suppresses scope enforcement for legitimate cross-cutting work
- [ ] AC-scope-telemetry: Scope violations emit events with session mode, file count, and file list for post-incident analysis
- [ ] AC-scope-tests: Test suite covers per-mode limits, circuit breaker threshold, bypass, and worktree exemption
```
