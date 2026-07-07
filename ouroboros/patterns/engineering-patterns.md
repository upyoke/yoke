# Engineering Patterns

Cross-link back from the [pattern catalog](../patterns.md) for the full Ouroboros index.

## P-1: Task spec quality directly determines implementation velocity

**First observed:** 2026-02-24 (worktree-isolation/001 engineer)
**Promoted:** 2026-02-24
**Occurrences:** 5+ entries across engineer and tester agents
**Status:** Active — ongoing design principle

Clear, complete task specs with precise acceptance criteria, exact file lists, and grep-based verification criteria let Engineers implement in minutes and Testers verify in one pass. Vague or stale specs cause false starts and extra round-trips. The worktree-isolation/001 task spec is a good reference template.

**Action:** Architect should use worktree-isolation/001 as a reference for task spec quality. Acceptance criteria should be machine-verifiable where possible (grep patterns, file existence checks, command output).

---

## P-2: PRD codebase context is highest-leverage content

**First observed:** 2026-02-23 (YOK-64 architect)
**Promoted:** 2026-02-24
**Occurrences:** 4+ entries across architect and PM agents
**Status:** Addressed (PRDs deprecated by YOK-216; principle carries forward to spec writing)

PRDs that include (1) current file contents of key files being modified, (2) decomposition hints ("use one worktree, not multiple"), and (3) pre-enumerated affected file lists eliminate redundant agent file reads and produce better plans. PRDs without codebase context force every downstream agent to re-read the same files.

**Action:** PRD template included "Codebase Context" and "Implementation Hints" sections. PRDs deprecated; principle applies to backlog item specs written by `/yoke promote`.

---

## P-3: Doc-only and micro-tasks need lighter verification

**First observed:** 2026-02-24 (worktree-isolation/001 tester)
**Promoted:** 2026-02-24
**Occurrences:** 4+ entries across tester agents
**Status:** Active — no formal lightweight verification path exists

For tiny additive changes (one-line template edits, doc-only updates), the full dispatch cycle (Engineer agent + Tester agent + review file) has high overhead relative to change size. Doc-only tasks should be labeled "verification-only" in the task spec so testers know no test execution is expected.

**Action:** Task specs for doc-only changes should include `test_mode: verification-only`. Engineers should paste verification output in update notes. SKILL.md-only items confirmed as fastest item type (see P-20).

---

## P-4: High-traffic files accumulate parallel conflict risk

**First observed:** 2026-02-23 (YOK-64 PM, simulator)
**Promoted:** 2026-02-24
**Occurrences:** 5+ entries across PM, engineer, simulator agents
**Status:** Partially addressed (shared logic extracted to scripts; SKILL.md splitting ongoing)

Files like `advance/SKILL.md` are modified by many tickets. Duplicate logic paths drift apart. The worktree-isolation epic's feature branch directly conflicted with parallel accelerated-flow changes to the same file.

**Action:** Extracted shared logic into scripts (YOK-66, YOK-73 done). Keep SKILL.md files focused (YOK-84 tracked). Sprint-db.sh cmd_init() merge conflicts (SINAI sprint T5) confirmed this pattern persists for additive DB schema changes.

---

## P-5: Test artifacts should be preserved for auditability

**First observed:** 2026-02-24 (worktree-isolation/001 tester)
**Promoted:** 2026-02-24
**Occurrences:** 3+ entries across tester agents
**Status:** Partially addressed (test-helpers.sh extracted, YOK-240 done)

Engineers run ad-hoc tests during implementation but don't save the test scripts or capture output. Testers must reconstruct tests from scratch. Saving test scripts to a known location and including verification output in commit notes improves auditability.

**Action:** Engineers should capture test output in update notes. Shared test-helpers.sh (YOK-240) provides reusable setup and assertion infrastructure.

---

## P-6: POSIX sh pitfalls cause recurring debugging cycles

**First observed:** 2026-02-24 (multiple engineers)
**Promoted:** 2026-02-28 (curate cluster 6)
**Occurrences:** 9+ entries across engineer, tester, conductor agents
**Status:** Addressed — AGENTS.md "POSIX sh pitfalls" section added (YOK-243 done)

Recurring footguns: `set -e` kills on false `&&` in while loops; `$()` loses variable assignments; `pipe | while read` loses variables; `|| var=""` discards stdout on intentional non-zero exit; heredoc quoting breaks JSON. Each costs a debugging cycle.

**Specific sub-patterns:**
- `set -e` + `[ condition ] && command` in subshells: false condition causes non-zero exit
- `$(setup_function)` subshell loses global variable assignments (3+ occurrences in test scripts)
- `|| var=""` on command substitution: discards stdout when captured command uses non-zero exit intentionally (doctor.sh HC-missing-gh-issues-32 bug)
- Python heredoc argument passing: `python3 << 'EOF' arg1` doesn't pass args; must use `python3 - arg1 << 'EOF'`

**Action:** AGENTS.md now documents `set -e` + pipelines, subshell variable scoping, unquoted variable splitting, `local` as accepted deviation, and arithmetic patterns.

---

## P-7: Hardcoded counts drift across documentation files

**First observed:** 2026-02-25 (sprint-system simulator)
**Promoted:** 2026-02-28 (curate cluster 2)
**Occurrences:** 14+ entries across simulator, engineer, architect, PM agents
**Status:** Addressed — YOK-184 (remove drifting counts) and YOK-271 (dynamic HC count) both done

HC count, script count, command count, nested skill count — all go stale when new items are added. Multiple docs (AGENTS.md, README.md, OVERVIEW.md, scripts.md, commands.md) each hardcode counts independently.

**Action:** YOK-184 removed all hardcoded numeric counts from docs. YOK-271 made doctor.sh HC count dynamic via `TOTAL_COUNT`. Pattern is now structurally prevented.

---

## P-8: Task specs reference brittle line numbers instead of semantic anchors

**First observed:** 2026-02-24 (worktree-isolation tester)
**Promoted:** 2026-02-28 (curate cluster 3)
**Occurrences:** 11+ entries across tester, engineer, architect agents
**Status:** Addressed — YOK-241 (Architect semantic anchors convention) done

Task specs reference absolute line numbers that shift when earlier tasks modify the same files, causing wasted time re-locating code. Agents recommend semantic anchors ("the `gh issue edit` label-swap call") or content-based patterns.

**Action:** Hard Constraint #10 added to `yoke-architect.md` requiring semantic anchors instead of line numbers.

---

## P-9: Engineers claim results in commit messages without verifying

**First observed:** 2026-02-28 (task 008 tester)
**Promoted:** 2026-03-01
**Occurrences:** 3+ entries (task 008 "all pass" claim, YOK-240 missing git add, test-dry-run.sh Test 12)
**Status:** Addressed — YOK-262 (Engineer post-commit verification) done

Engineers commit with messages claiming "all tests pass" or "file added" without verifying. YOK-240 committed but forgot to `git add` the new test-helpers.sh.

**Action:** `git status --porcelain` check added to Engineer step 7 in `yoke-engineer.md`. Rule: verify after committing, flag untracked files that should have been included.

---

## P-10: Combined-scope tasks (tests + docs) cause partial completion

**First observed:** 2026-02-28 (YOK-195 conductor, task 008)
**Promoted:** 2026-03-01
**Occurrences:** 3+ entries across conductor and tester agents
**Status:** Addressed — YOK-210 (split combined-scope tasks) and YOK-265 (same-file sequencing) both done

Task 008 combined regression tests AND documentation updates. Engineer completed tests but omitted all 5 doc files. Engineers naturally gravitate toward code-adjacent work and deprioritize documentation. 73 minutes vs. 15-minute median.

**Action:** Architect Hard Constraint #11 (YOK-265) requires same-file tasks to be sequenced. Convention: split "code + docs" into separate tasks.
