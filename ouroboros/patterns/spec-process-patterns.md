# Spec & Process Patterns

Cross-link back from the [pattern catalog](../patterns.md) for the full Ouroboros index.

## P-29: PRD template improvements (multiple sub-patterns)

**First observed:** 2026-02-25 (sprint-system PM)
**Promoted:** 2026-02-28 (curate cluster 8)
**Occurrences:** 12+ entries across PM agents
**Status:** Addressed — PRDs deprecated by YOK-216; Shepherd+Boss replaces

Multiple PM agents suggested: "Known Limitations" section, "Canonical Sources" with file/line references, "Files to Change" enumeration, "Risk Register" for high-risk files, decomposition hints, resolved-vs-open question formatting.

**Action:** PRDs deprecated. The principle of rich codebase context in specs carries forward to `/yoke promote` (see P-2).

---

## P-30: Nested worktree creation from wrong CWD

**First observed:** 2026-03-01 (T5 conductor, YOK-251)
**Promoted:** 2026-03-01
**Occurrences:** 2+ entries
**Status:** Addressed — YOK-261 (create-issue-worktree.sh CWD guard) done

Advancing YOK-251 while CWD was inside YOK-219's worktree created a nested `.worktrees/issue-YOK-219/.worktrees/issue-YOK-251/` path. `git rev-parse --show-toplevel` returns the worktree root, not the main repo root.

**Action:** YOK-261 added guard comparing `--git-dir` with `--git-common-dir` to detect worktrees. The advance SKILL.md enforces CWD at repo root for done transition but not active transition — the CWD guard in the script catches this.

---

## P-31: Bookkeeping operations correctly exempt from worktree discipline

**First observed:** 2026-02-24 (post-YOK-87 review)
**Promoted:** 2026-03-01
**Occurrences:** 3+ entries
**Status:** Resolved — design tension settled

`/yoke idea` and `/yoke advance` modify `yoke/backlog/` and `BOARD.md` on main. Design tension: backlog is shared state on main, but rules say don't touch main.

**Action:** Resolved: planning activities go directly to main (DB writes and shared state). Worktree mandate applies to implementation code changes only. Documented in `accelerated-flow.md` under "Planning on Main."

---

## P-32: Explore subagent should provide richer pre-scans

**First observed:** 2026-02-26 (YOK-163 PM, YOK-167 PM)
**Promoted:** 2026-03-01
**Occurrences:** 5+ entries across PM agents
**Status:** Addressed — subsumed by the dedicated research-lane idea now parked in PAD.md

Explore subagent provides file paths and line numbers but not concrete variable values, function signatures, or spec accuracy checks. PM agents had to re-read files to verify claims.

**Action:** A future scholar-style research lane should provide structured codebase context with web access. Supersedes Explore for PM-facing pre-scans.

---

## P-33: Sprint-db.sh merge conflicts from concurrent additive schema changes

**First observed:** 2026-03-01 (T5 conductor)
**Promoted:** 2026-03-01
**Occurrences:** 3+ merge conflicts (YOK-251, YOK-252, YOK-253 all inserting CREATE TABLE blocks)
**Status:** Active — no prevention mechanism

Multiple items adding tables to the same cmd_init() function cause sequential merge conflicts despite being purely additive. Each merge requires manual conflict resolution.

**Action:** Architect decomposition should either bundle additive-only changes to the same function into one item, or sequence branches so each rebases on the merged predecessor.

---

## P-34: Trial-merge pre-flight would catch integration bugs automatically

**First observed:** 2026-02-28 (YOK-196 T2 conductor)
**Promoted:** 2026-03-01
**Occurrences:** 4+ idea entries across conductors
**Status:** Not yet implemented

The simulator should include a `git merge --no-commit --no-ff main` step in a temp clone to detect: (1) merge conflicts, (2) auto-merged files with conditional else-block references, (3) post-merge test results. Would have caught YOK-196 GAP #1 automatically.

**Action:** Proposed `trial-merge.sh <branch> [target]` helper script. Integration simulation currently reads branch files only, not post-merge state.

---

## P-35: Mock gh JSON in heredocs breaks on newline interpretation

**First observed:** 2026-02-26 (github-comment-sync/004 engineer)
**Promoted:** 2026-03-01
**Occurrences:** 3+ entries across engineer agents
**Status:** Active — testing convention established but not formally documented

`echo` on macOS interprets `\n` as literal newlines in JSON strings, producing invalid JSON. Fix: write mock JSON to a file via python3 and `cat` from the mock script. File-based mock responses avoid heredoc escape issues entirely.

**Action:** Pattern documented in test-body-sync.sh and used in HC-body-drift tests. Should be added to test-writing conventions.

---

## P-36: Config keys scattered with no central index

**First observed:** 2026-02-26 (YOK-156, YOK-167 PM agents)
**Promoted:** 2026-03-01
**Occurrences:** 4+ entries
**Status:** Active — machine-config/schema docs are the index

No cross-reference from SKILL.md files to their config keys. A developer reading a SKILL.md has no pointer to the config key controlling its behavior. The machine-config/schema documentation is the only index, with no grouping by workflow stage.

**Action:** Recommendation: add `## Config Keys` section to each SKILL.md listing relevant keys, defaults, and effects. Or add a `## Config` section to SKILL.md that names keys and points to the machine-config/schema documentation.

---

## P-37: User-authored vs Yoke-managed file classification gap

**First observed:** 2026-02-24 (safe-worktree-lifecycle PM)
**Promoted:** 2026-03-01
**Occurrences:** 3+ entries (YOK-91 incident core pattern)
**Status:** Partially addressed (YOKE_SHARED_FILES allowlist)

No concept of "user-authored but uncommitted" files. `git checkout --` that safely resets status files destroys user-authored uncommitted work. PAD.md was destroyed this way.

**Action:** YOKE_SHARED_FILES allowlist (YOK-235 expanded) prevents destruction. Deeper fix: a classification system for files at the Yoke/user boundary.

---

## P-38: SKILL.md-only tasks need specialized testing path

**First observed:** 2026-03-01 (YOK-275 tester)
**Promoted:** 2026-03-02
**Occurrences:** 6 entries across tester, engineer agents
**Status:** Active — no formal verification path for instruction-only tasks

Documentation/SKILL.md-only tasks have no executable tests, but the Tester process still requires "run tests" and "check worktree cleanliness." Agents write N/A for test-related fields, creating friction. The P-3 pattern (lighter verification for doc-only tasks) identified this gap but no specialized review checklist exists.

**Action:** Proposal: a `task_type: instruction-only` marker in task specs that triggers a specialized Tester checklist focused on prose correctness, contract alignment, and scenario coverage instead of test execution. Extends P-3 and P-20.

---

## P-39: Cross-track dirty files block merge with exit 4

**First observed:** 2026-03-01 (T2 conductor)
**Promoted:** 2026-03-02
**Occurrences:** 4 entries across conductor sessions
**Status:** Active — YOKE_SHARED_FILES incomplete

Parallel track sessions produce uncommitted artifacts on main — epic status files (`dashboard.md`), progress notes, backlog items auto-ingested from other tracks, and `PAD.md`. `merge-worktree.sh` exit 4 blocks on these. The YOKE_SHARED_FILES list doesn't include epic status directories or user notes.

**Action:** Expand YOKE_SHARED_FILES to include `yoke/epics/*/status/*` and `PAD.md`. Extends P-13 and P-15. The pre-merge dirty-file sweep (P-15) remains the deeper fix.

---

## P-40: Task spec accuracy — counts, subcommand refs, and stale references

**First observed:** 2026-03-01 (epic-data-migration engineer)
**Promoted:** 2026-03-02
**Occurrences:** 10 entries across engineer, tester, conductor agents
**Status:** Active — no automated validation

Architect-generated task specs contain systematic accuracy issues: (1) numeric claims don't match enumerated items, (2) subcommand references that don't exist in dependencies, (3) "Files Touched" sections missing test files, (4) FR references that don't resolve to documents, (5) specs going stale between plan and execution.

**Action:** Add Architect Hard Constraint: numeric claims must match enumerated items. "Files Touched" must include test files when tests are required. Subcommand references must exist in the dependency task's implementation. Extends P-8 (semantic anchors).

---

## P-41: DB helpers duplicated across -db.sh scripts

**First observed:** 2026-03-01 (yoke-db-router engineer)
**Promoted:** 2026-03-02
**Occurrences:** 3 entries from engineer agents
**Status:** Active — no shared library exists

`_resolve_root()`, `_require_db()`, `_escape()`, `_sql()`, `_sql_query()`, `_sql_scalar()` are copy-pasted identically across ouroboros-db.sh, release-notes-db.sh, tracks-db.sh, and yoke-db.sh epic. Each also embeds `PRAGMA journal_mode=WAL` inline.

**Action:** Extract into a shared `db-helpers.sh` that all domain -db.sh scripts source. Set WAL mode once during init rather than per-query.

---

## P-42: yoke-db.sh fails from worktree CWD

**First observed:** 2026-03-01 (T2 conductor)
**Promoted:** 2026-03-02
**Occurrences:** 3 entries from conductor sessions
**Status:** Active — worktree CWD causes DB path resolution failure

`yoke-db.sh` and `done-transition.sh` fail when CWD is inside a worktree because `YOKE_ROOT` resolves via `git rev-parse --show-toplevel` to the worktree path instead of the main repo where `yoke.db` lives. Multiple related CWD bugs have been fixed (YOK-25, 89, 102, 144, 178, 261) but the root cause in `yoke-db.sh` itself persists.

**Action:** `yoke-db.sh` should use `git rev-parse --git-common-dir` to resolve the main repo root, matching the guard added in `create-issue-worktree.sh` (YOK-261).

---

## P-43: done-transition.sh exit code 5 after successful merge

**First observed:** 2026-03-01 (T1 conductor, YOK-298)
**Promoted:** 2026-03-02
**Occurrences:** 4 entries from conductor sessions (YOK-298, YOK-303)
**Status:** Active — tracked as YOK-322

`done-transition.sh` exits with code 5 even though the PR merged successfully on GitHub. Output shows duplicated lines suggesting double-execution. Requires manual `yoke-db.sh items update N status done` as workaround. Root cause appears to be in post-merge section — possibly triggered by hooks.

**Action:** YOK-322 filed. Investigate whether hooks trigger re-execution of done-transition.sh, and add idempotency guards to post-merge steps.

---

## P-45: Tester review file no-shows require skeleton-first pattern

**First observed:** 2026-03-01 (epic-data-migration tester)
**Promoted:** 2026-03-02
**Occurrences:** 3 entries across tester, conductor agents
**Status:** Active — extends P-25

Tester subagents sometimes crash or run out of turns before producing a review file — total loss. Retry escalation works but costs an extra subagent invocation. The proposed fix: instruct Testers to write the review skeleton (headers, verdict template) FIRST, then fill in results. Partial completion still produces a parseable verdict.

**Action:** Add "write review skeleton before testing" instruction to `yoke-tester.md`. Extends P-25 (Tester reliability).

---

## P-46: Global PreToolUse Bash hooks are not a sufficient guard for subagents

**First observed:** 2026-03-02 (YOK-296)
**Promoted:** 2026-03-02
**Occurrences:** 1 confirmed bypass case (subagent executed direct `sqlite3` with hardcoded DB path)
**Status:** Mitigated — defense-in-depth added

A direct `sqlite3` command ran inside an Agent-tool subagent session without being blocked by the expected global `PreToolUse` lint hook. **YOK-933 update (2026-03-17):** Empirical testing confirmed that global `settings.json` hooks DO fire for subagents (both inline Explore and formal agents). The original bypass was likely due to payload-shape drift or an incomplete blocklist, not hook non-propagation. The frontmatter hooks added as mitigation still provide valuable defense-in-depth redundancy.

**Action:** Added `PreToolUse`/`Bash` wiring for the DB-command guard (today `lint_db_cmd`; legacy stable id `lint-sqlite-cmd`) directly in all Bash-capable Yoke agents. Also hardened the guard to log payload parse/missing-command warnings instead of silent fail-open.

---

## P-47: Single-worktree accelerated epic flow for tightly-coupled tasks

**First observed:** 2026-03-02 (YOK-290, 7 tasks on 1 worktree)
**Promoted:** 2026-03-02
**Occurrences:** 2 (YOK-290: 7 tasks, YOK-197: 7 tasks)
**Status:** Active — confirmed effective pattern

For epics where tasks are tightly coupled or touch disjoint files, using a single worktree for all tasks and implementing sequentially eliminates per-task sync/dispatch/merge ceremony. The flow: advance active → implement all tasks in sequence → advance done. No merge conflicts within the epic because there's only one branch. YOK-290 completed 7/7 tasks with zero rework; YOK-197 completed 7/7 tasks the same way.

Distinct from P-23 (sequential worktree strategy, which creates multiple worktrees). This pattern uses ONE worktree and avoids merge entirely during implementation. Best for: disjoint-file epics, tightly-coupled task sequences, accelerated flow items.

**Action:** Use when tasks don't need individual PR review. Not suitable for epics where tasks have independent reviewers or need isolated CI validation.

---

## P-48: Audit-to-execution handoff via backlog item body

**First observed:** 2026-03-02 (YOK-340 audit → YOK-348 execution)
**Promoted:** 2026-03-02
**Occurrences:** 2 (YOK-340/YOK-348 pair, ouroboros entry 213)
**Status:** Active — confirmed effective pattern

Writing detailed audit findings (with line numbers, exact text to change, specific recommendations) directly into a backlog item body creates a clean handoff: the next session reads the body and knows exactly what to fix. YOK-340 produced a structured audit comparing README.md vs README-FUTURE.md with 6 specific fixes. YOK-348 consumed that as a mechanical checklist and completed all 6 in one pass with zero ambiguity.

**Action:** For investigation/audit items, write findings as structured checklists in the item body. For execution items that consume audits, reference the audit item body directly. The pattern: audit item produces spec, execution item consumes it.

---

## P-50: SKILL.md files growing past agent read limits

**First observed:** 2026-03-02 (conductor, shepherd agents)
**Promoted:** 2026-03-05
**Occurrences:** 8+ entries across conductor, shepherd, product-manager agents
**Status:** Active — ticket filed: YOK-502

`conduct/SKILL.md` at 1453 lines (~26K tokens) exceeds the 25K token Read tool limit. Agents must read in chunks, losing cross-reference context. The file is also the most-edited file in the project, causing merge conflicts. Extends P-4 (high-traffic files) with a new dimension: agent context window exhaustion.

**Action:** YOK-502 filed. Split into sub-files: router + single-item + batch-flow + error-handling + subagent-dispatch. Target: no file >500 lines / 10K tokens.

---

## P-51: Body write path opacity — 4+ files to trace content flow

**First observed:** 2026-03-03 (product-manager, shepherd agents)
**Promoted:** 2026-03-05
**Occurrences:** 6+ entries across product-manager, shepherd agents
**Status:** Active — ticket filed: YOK-503

Understanding how body content flows from agents → DB → GitHub → .md requires reading 4+ files (~2,800 lines). No single document maps the path. PM agents report 30+ minutes of exploration just to understand body persistence. Root cause of YOK-476 (body replacement loses specs) and YOK-459 (auto-sync swallows failures).

**Action:** YOK-503 filed. Document write paths in db-reference.md, then consolidate into a single function.

---

## P-52: Execution-type deliverables require explicit verification before done-transition

**First observed:** 2026-03-09 (YOK-628 bootstrap-project.sh)
**Promoted:** 2026-03-10
**Occurrences:** 1 confirmed instance (YOK-628/YOK-656/YOK-657)
**Status:** Active — process discipline pattern, no automated guard

Some backlog items have deliverables that go beyond code: running a script against a target, configuring secrets, verifying infrastructure exists. YOK-628 was marked done after the script was implemented and tested, but the script was never executed against the Buzz repo. The gap went undetected because ephemeral workflows from a separate effort (YOK-618) created the appearance that "some workflows exist."

**Root cause taxonomy:** This is a subclass of P-9 (claiming results without verifying) but distinct because the unverified deliverable is operational execution, not code correctness. Standard testing (unit tests, tester agent) validates that code works correctly but does not validate that operational steps were performed.

**Decision: Process discipline over automated tooling.** After evaluation, the recommended approach is discipline-based rather than automated:

1. **Item specs must distinguish code deliverables from execution deliverables.** When an item's Definition of Done includes operational steps (run a script, configure secrets, deploy infrastructure), those steps should be listed explicitly as separate acceptance criteria, not bundled with "code is correct."

2. **Agents marking done should verify each acceptance criterion individually.** The advance-to-done flow already requires AC verification, but agents under context pressure may treat "code works" as sufficient. The lesson: execution deliverables are not implied by passing tests.

3. **Automated verification is not justified at this time.** A generic "verify execution" hook in the advance flow would require per-item-type verification logic (what does "executed" mean for a bootstrap script vs. a migration vs. a deployment?). The engineering cost exceeds the benefit given this is the first occurrence.

4. **Tester agents should flag unverified execution ACs.** When a tester reviews an item with operational ACs, they should explicitly note whether execution evidence exists (logs, API responses, workflow files on target repos) rather than only validating code correctness.

**Action:** This pattern serves as the institutional memory. If a second occurrence is observed, escalate to an automated guard (e.g., `advance` skill prompting for AC-by-AC confirmation before done-transition). Extends P-9 (verify before claiming done) and P-26 (documentation-as-enforcement limitations).
