# Ouroboros — Learning Patterns

Recurring patterns promoted from the Ouroboros learning log. Each entry tracks when a pattern was first observed, when it was promoted, and what action was taken. Patterns are preserved as institutional memory regardless of whether they have been addressed — the **Status** field on each pattern tracks resolution.

This file is the **catalog**: pattern IDs, titles, and one-line summaries grouped by topic. Click through to the per-topic files for full pattern bodies (problem statement, occurrences, status, remediation actions).

---

## Engineering Patterns

Full bodies in [patterns/engineering-patterns.md](patterns/engineering-patterns.md).

- **P-1: Task spec quality directly determines implementation velocity.** Clear, machine-verifiable ACs let Engineers implement quickly and Testers verify in one pass. (Active)
- **P-2: PRD codebase context is highest-leverage content.** Specs that bundle current file contents and pre-enumerated affected files cut redundant agent exploration. (Addressed — PRDs deprecated)
- **P-3: Doc-only and micro-tasks need lighter verification.** Full Engineer + Tester dispatch is high overhead for tiny additive changes. (Active)
- **P-4: High-traffic files accumulate parallel conflict risk.** Files like `advance/SKILL.md` get edited by many tickets — extract shared logic and split SKILL.md files. (Partially addressed)
- **P-5: Test artifacts should be preserved for auditability.** Engineers should capture test output in update notes; shared test-helpers.sh provides reusable infrastructure. (Partially addressed)
- **P-6: POSIX sh pitfalls cause recurring debugging cycles.** `set -e`, subshell variable scoping, `pipe | while read`, heredoc quoting are the recurring footguns. (Addressed)
- **P-7: Hardcoded counts drift across documentation files.** HC counts and similar magic numbers go stale across multiple docs. (Addressed — counts removed and dynamic)
- **P-8: Task specs reference brittle line numbers instead of semantic anchors.** Line numbers shift; semantic anchors (function names, content patterns) are durable. (Addressed)
- **P-9: Engineers claim results in commit messages without verifying.** "All tests pass" / "file added" without actually verifying. (Addressed — post-commit verification step)
- **P-10: Combined-scope tasks (tests + docs) cause partial completion.** Engineers gravitate to code-adjacent work; split combined scopes into separate tasks. (Addressed)

## Merge & Integration Patterns

Full bodies in [patterns/merge-integration-patterns.md](patterns/merge-integration-patterns.md).

- **P-11: Merge-worktree.sh rebase fails with cascading conflicts on parallel branches.** Long-lived parallel branches need a merge-commit fallback strategy. (Partially addressed)
- **P-12: Cross-epic parallel development creates invisible naming mismatches.** `_query_item` vs `query_item` works in isolation, breaks on integration — only post-merge simulation catches it. (Active)
- **P-13: Dirty repo root from parallel sessions blocks merge.** Uncommitted release notes / doctor.sh / backlog files trip exit 4. (Partially addressed)
- **P-14: Generated files not in auto-resolve list cause avoidable merge conflicts.** Health reports, BOARD.md (pre auto-resolve) collide between worktrees and main. (Active for health reports)
- **P-15: Pre-merge dirty-file sweep eliminates one-by-one discovery friction.** A single sweep before the merge phase removes the 4-retry discovery cycle. (Not yet implemented)

## Shell & Tooling Patterns

Full bodies in [patterns/shell-tooling-patterns.md](patterns/shell-tooling-patterns.md).

- **P-16: zsh != history expansion corrupts SQL operators.** `<>` is the only safe not-equal operator under the Bash tool's zsh shell. (Resolved — hook blocks both `!=` and `\!=`)
- **P-17: Stale lock directories block board rebuilds in parallel sessions.** `BOARD.md.lock` needs PID-liveness or age-based auto-cleanup. (Active)
- **P-18: Test environment mock setups missing new dependencies.** Adding a new `source` to a script breaks every test that mocks that script's directory. (Active)
- **P-19: YOKE_DRY_RUN=1 causes false test failures.** Tests use mock `gh` scripts that never fire when scripts skip `gh` calls. (Addressed — never set DRY_RUN in tests)

## Workflow & Velocity Patterns

Full bodies in [patterns/workflow-velocity-patterns.md](patterns/workflow-velocity-patterns.md).

- **P-20: SKILL.md-only tasks are the fastest item type.** 2-5 min average; classify XS/S in sizing. (Active heuristic)
- **P-21: Conductor pattern (orchestrating full track execution) is effective.** Sequential dispatch then sequential merge keeps each merge against fully-resolved main. (Active)
- **P-22: Accelerated flow is efficient for small-to-medium issues.** advance → implement → test → merge → done in ~5-15 min per item. (Active core pattern)
- **P-23: Sequential worktree strategy works cleanly for track execution.** Create all worktrees upfront, engineer in each, then merge in sequence. (Active)
- **P-24: Simulation-fix-resimulate cycle converges in 1-2 rounds.** Plan-phase simulation catches real gaps; Architect fixes in one iteration. (Active)

## Agent Behavior Patterns

Full bodies in [patterns/agent-behavior-patterns.md](patterns/agent-behavior-patterns.md).

- **P-25: Tester reliability is the biggest conductor time sink.** Reviews directory missing, Tester not writing the file. (Partially addressed; auto-retry remaining)
- **P-26: Documentation-as-enforcement fails under context pressure.** "You MUST" in SKILL.md is a probabilistic constraint — prefer code-level enforcement. (Active design principle)
- **P-27: Agent stall pattern at phase boundaries.** Multi-minute hang after large subagent results; YOK-529 added five mitigation layers. (Mitigated)
- **P-28: Worktree limits block parallel track execution.** `max_active_worktrees` should auto-scale with track count. (Active)

## Spec & Process Patterns

Full bodies in [patterns/spec-process-patterns.md](patterns/spec-process-patterns.md).

- **P-29: PRD template improvements (multiple sub-patterns).** Known limitations, canonical sources, files-to-change, risk register. (Addressed — PRDs deprecated)
- **P-30: Nested worktree creation from wrong CWD.** `git rev-parse --show-toplevel` returns the worktree root. (Addressed — CWD guard)
- **P-31: Bookkeeping operations correctly exempt from worktree discipline.** Planning activities go directly to main. (Resolved)
- **P-32: Explore subagent should provide richer pre-scans.** Future scholar-style research lane will supersede Explore for PM pre-scans. (Addressed — parked in PAD.md)
- **P-33: Sprint-db.sh merge conflicts from concurrent additive schema changes.** Architect should bundle additive same-function changes into one item. (Active)
- **P-34: Trial-merge pre-flight would catch integration bugs automatically.** `git merge --no-commit --no-ff` in a temp clone. (Not yet implemented)
- **P-35: Mock gh JSON in heredocs breaks on newline interpretation.** Use file-based mock responses to avoid macOS `echo \n` interpretation. (Active convention)
- **P-36: Config keys scattered with no central index.** Add `## Config Keys` section to each SKILL.md or central index. (Active)
- **P-37: User-authored vs Yoke-managed file classification gap.** YOKE_SHARED_FILES allowlist; deeper classification still needed. (Partially addressed)
- **P-38: SKILL.md-only tasks need specialized testing path.** `task_type: instruction-only` marker for prose-correctness review. (Active proposal)
- **P-39: Cross-track dirty files block merge with exit 4.** Expand YOKE_SHARED_FILES; deeper fix is the pre-merge sweep (P-15). (Active)
- **P-40: Task spec accuracy — counts, subcommand refs, and stale references.** Numeric claims, FR refs, and Files Touched sections drift. (Active)
- **P-41: DB helpers duplicated across -db.sh scripts.** Extract `_resolve_root` / `_require_db` / `_sql*` into a shared library. (Active)
- **P-42: yoke-db.sh fails from worktree CWD.** Use `git rev-parse --git-common-dir` to resolve main repo root. (Active)
- **P-43: done-transition.sh exit code 5 after successful merge.** Possible double-execution from hooks; tracked as YOK-322. (Active)
- **P-45: Tester review file no-shows require skeleton-first pattern.** Write the review skeleton first so partial completion still parses. (Active — extends P-25)
- **P-46: Global PreToolUse Bash hooks are not a sufficient guard for subagents.** Per-agent hook wiring added as defense-in-depth. (Mitigated)
- **P-47: Single-worktree accelerated epic flow for tightly-coupled tasks.** One worktree for all tasks; no per-task merge ceremony. (Active — distinct from P-23)
- **P-48: Audit-to-execution handoff via backlog item body.** Audit items produce structured checklists; execution items consume them mechanically. (Active)
- **P-50: SKILL.md files growing past agent read limits.** `conduct/SKILL.md` >25K tokens; split into router + sub-files. Tracked as YOK-502. (Active)
- **P-51: Body write path opacity — 4+ files to trace content flow.** Document write paths in db-reference.md and consolidate. Tracked as YOK-503. (Active)
- **P-52: Execution-type deliverables require explicit verification before done-transition.** Subclass of P-9 — operational steps are not implied by passing tests. (Active discipline pattern)

## Patterns from 2026-04-04 Curate (1685 entries)

Full bodies in [patterns/curate-2026-04-04-patterns.md](patterns/curate-2026-04-04-patterns.md).

- **P-53: Specs with phantom code references waste engineering time.** Single largest source of wasted engineering time; refine/polish/PM/Boss now check explicitly. (Partially addressed)
- **P-54: Blast radius needs grep discovery, not hardcoded file lists.** Refine requires discovery commands; prd-validate.sh blocks rename-heavy specs that omit them. (Partially addressed)
- **P-55: Engineers complete core implementation but skip peripheral ACs.** Polish now treats peripheral ACs and test co-modification as mandatory. (Partially addressed)
- **P-56: Self-consistency drift within specs and plans.** Refine and Boss require self-consistency checks; no general contradiction linter yet. (Partially addressed)
- **P-57: Error and rollback paths consistently omitted from specs.** prd-validate.sh, PM template, and Boss now block missing failure/recovery coverage on state-changing work. (Addressed on the spec path)
- **P-58: Never destroy un-inventoried state before migrating or recording its contents.** A cleanup pass destroyed 4,095 rows of telemetry in a mislocated DB file. The control plane is now Postgres-native and worktree-local DB files are refused at the connection boundary, but the rule generalizes to any "stray" state. (Addressed; permanent negative example)
