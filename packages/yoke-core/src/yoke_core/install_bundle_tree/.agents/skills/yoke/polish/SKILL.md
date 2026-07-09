---
name: polish
description: "Review code and tests in existing worktree lane(s) against item artifacts, make finishing fixes, run verification, and commit."
argument-hint: "{YOK-N}"
---

# /yoke polish {YOK-N}

Standalone capability for polishing an in-progress implementation. Locates the existing implementation worktree lane set for a backlog item, reviews code and tests against the item's artifacts (spec, ACs, technical plan), makes finishing fixes, runs verification, and commits when changes are needed. Issue items usually have one item worktree; epic items may have multiple task worktrees from the worktree plan.

This is an explicit, operator-invoked capability that Codex can execute directly. It does not require `/yoke do`, lane-aware routing, or lifecycle-family ownership wiring.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug not worth a ticket, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Arguments

- `{YOK-N}` — Backlog item ID. Accepts `YOK-N`, zero-padded IDs, or a bare number.

## Modes

Polish always advances status on successful completion, whether invoked directly (e.g., `/yoke polish YOK-N`) or via scheduler routing.

### Lifecycle transitions
- `reviewed-implementation` -> `polishing-implementation` (set immediately when polish starts)
- `polishing-implementation` -> `implemented` (set on successful completion)

If polish fails, cannot resolve the worktree, or leaves verification failing, the item must NOT auto-advance to `implemented`. Once polish starts, the item stays at `polishing-implementation`.

## Constraints

- Requires existing implementation worktree lanes. If no lane exists, stop with guidance.
- Code edits and test fixes are expected when needed.
- Commits follow standard Yoke commit discipline (specific files, descriptive messages).
- Both standalone and routed modes advance status on successful completion.
- Respect existing uncommitted work in the item's worktree. Do not discard or reset unrelated edits.
- **Never push branches or create pull requests.** Polish commits locally only. Pushing and PR creation belong to usher.

## Philosophy

**The implementation must be complete end-to-end.** If the operator can't use and experience the result after this branch merges, the work isn't done. A feature that's wired up internally but not reachable from the UI/CLI/workflow where users encounter it is unfinished. Help text that still describes the old behavior is unfinished. A config key that's read but never documented is unfinished. Polish traces the full user journey and closes every gap.

**Clean-slate after every change.** After this branch merges, the codebase should read as if the old way never existed. That means:
- No comments like "this used to work like X" or "previously this was Y" — rewrite to describe the present.
- No compatibility shims, re-exports, or aliases for things that were renamed or removed — just use the new name everywhere.
- No defensive code or error handling for states that can no longer occur after this change.
- No "just in case" fallbacks for scenarios that aren't real.
- No stale TODOs, FIXMEs, or "remove after migration" comments when the migration is complete.

**Dead weight has zero tolerance.** If the implementation obsoletes something, that something must be deleted — not left behind. This includes: orphaned utility functions that only served removed code, test fixtures and mocks that only exercised removed behavior, config keys and feature flags for features that no longer exist, migration scripts for data that has already been fully cleaned up, documentation sections that describe removed functionality, and re-exports or type aliases that nothing imports.

**Simplest migration wins.** If the implementation includes migration logic, verify it's actually needed. If all the old data has already been cleaned up, delete the migration script. If there are no live consumers of the old interface, delete the compatibility shim. Default to hard cutover — only keep graceful migration when there's provably live data or users that need it.

**Be the giant.** We stand on inherited shoulders; leave a leg up for the next agent by making this artifact cold-start complete. Your polished code and commit messages are the cold-start context for the Tester, the reviewer, and every future developer who reads this code. Clean commits with descriptive messages, well-named functions, and accurate comments make verification trivial. Sloppy commits with "fix stuff" messages and leftover debug code force the next person to re-investigate what you already understood.

**No such thing as "agent error."** When the review reveals that the Engineer produced incomplete or incorrect code, never frame this as "the engineer made a mistake." The cause is always systemic: the task spec was ambiguous, an interface contract was incomplete, a file was too large for the agent to read fully (P-50: files past agent read limits cause context corruption), or the dispatch context was missing critical paths. Frame every issue as what the SYSTEM should change to prevent it. Fix the code, but also note the systemic cause for the review report.

**Events table for debugging.** When investigating unexpected behavior or test failures during polish, query the events table for recent telemetry: `yoke events tail --limit 20` or `yoke events anomalies --since "4 hours ago"`. Anomaly flags (nonzero_exit, benign_failure, generated_view_write) and tool call timing reveal what happened during the Engineer's session and whether the failure was systemic or code-specific.

**Think, don't just check.** The review dimensions in this skill are a starting point, not a ceiling. Before and after working through the checklist, step back and think about the implementation as a whole: Does this branch actually deliver what the ticket intended? Would the operator be satisfied using the result end-to-end? What would a thoughtful senior engineer notice that the checklist doesn't cover? Work top-down (from the ticket's purpose to the code) as well as bottom-up (from each file's diff to the overall picture). The checklist catches known failure modes; your judgment catches everything else. If something feels wrong, wasteful, incomplete, or fragile but doesn't match a specific review dimension, fix it or flag it anyway.

**Codebase-reader naming.** Assume future readers of the codebase will NOT have the ephemeral planning artifacts this branch was written from. During polish, rewrite any new or renamed file, module, helper, test, doc, command, event, config key, symbol, heading, or comment that explains itself by pointing at a ticket, strategy doc, plan, initiative, phase, task, AC/FR label, branch, worktree, or implementation batch. Polished code describes current function, purpose, mechanics, and domain role to a repository reader.

## Simplify Anchor (reuse / quality / efficiency)

The polish Philosophy above (`Clean-slate after every change`, `Dead weight has zero tolerance`, `Simplest migration wins`) IS the simplify three-axis vocabulary at the polish stage. The shared definition, including the future-concept pull-forward lens, lives in `AGENTS.md`'s `## Simplify — three-axis doctrine` section; polish anchors that vocabulary under explicit headings:

- **Reuse** — clean-slate after every change; rewrite to describe the present rather than amending; remove compatibility shims, re-exports, and aliases nothing imports.
- **Quality** — dead weight has zero tolerance; orphaned helpers, dead config, dead tests, defensive code for impossible states all get deleted; only non-obvious WHY comments remain; names and current-state docs describe current function/purpose/mechanics rather than planning provenance.
- **Efficiency** — simplest migration wins; default to hard cutover; flag unnecessary indirection, redundant computation, multi-step pipelines that could collapse into one operation; justify infrastructure against existing surfaces.
- **Future-concept lens** — if the diff touches actors, sessions, heartbeats, ownership, leases, claims, approvals, overrides, evidence, run records, journals, packets, locks, or shared-state coordination, treat the surface as an end-state v0 or require a deletion / absorption target.

Polish runs the three axes as a **single sequential pass** at the start of the polish flow (see the Named simplify pass below) — **NOT** parallel three-sub-agent fan-out. v0 keeps the pass sequential by design; parallel-fan-out is explicitly deferred to v1.

## Steps

Polish executes six phases in order. Each phase lives in its own file; read and execute them in sequence.

### Parse and claim (steps 1–3)
Read `.agents/skills/yoke/polish/parse-and-claim.md` and execute it. Parses the item argument, locates the existing worktree lane set via the resolver, and activates polish through the claim + status-transition hard gate. Stops immediately if the item is missing, the lane set does not exist, or the claim is held by another session.

### Gather context (steps 4–5)
Read `.agents/skills/yoke/polish/context.md` and execute it. Reads the item's spec, body, technical plan, and test results, then surveys recent main commits, active pipeline tickets, and recently-done tickets for drift, overlap, and supersession. All findings feed the review phase.

### Named simplify pass (worktree-diff-scoped)

**This is the first pass of polish.** Run it before the staleness/blast-radius review (the Review the implementation step) and before any test re-run — shrink the diff before re-validating.

The pass reviews the worktree diff against `main` along the three axes and future-concept lens from `AGENTS.md`'s `## Simplify — three-axis doctrine` section, applies fixes in place, and continues with the normal polish verification flow.

- **Scope:** implementation-worktree diffs only. For single-worktree items, inspect `git -C "{WORKTREE_PATH}" diff main...HEAD` plus any uncommitted changes. For multi-worktree epics, iterate every path in `WORKTREE_PATHS` and inspect each worktree's diff against `main`. **Do NOT expand to whole-repo cleanup** — that's deferred work, not polish.
- **Run sequentially as a single pass.** Walk the diff once; carry findings across all three axes simultaneously rather than three independent sweeps. Parallel three-sub-agent fan-out is **explicitly deferred to v1**.
- **Reuse:** Does the diff add a new file, helper, template, skill, event, command, or prompt surface that an existing one already covers? Replace with reuse. Does it duplicate an existing constant, type, or helper API? Collapse onto the existing one.
- **Quality:** Is each artifact at the smallest concrete shape that satisfies the request? Remove redundant state, parameter sprawl, copy-paste-with-variation, leaky abstractions, stringly-typed code where types/constants exist, unnecessary wrapper nesting, and unnecessary WHAT comments. Keep only non-obvious WHY comments.
- **Codebase-reader naming:** Are all new or renamed live surfaces named for current function/purpose/mechanics rather than for the ticket, plan, phase, task, AC, branch, worktree, or batch that produced them? Rename provenance-shaped surfaces in the polish diff.
- **Efficiency:** Is there redundant computation, repeated file reads, duplicate API calls, N+1 patterns, missed concurrency, hot-path bloat, recurring no-op updates, unnecessary existence pre-checks, unbounded structures, missing cleanup, or overly broad operations? Collapse them. New infrastructure proposed mid-polish must justify itself against existing surfaces.

**Anti-argumentation (verbatim):** **do not argue with the finding, just skip false positives.** A finding is a fix attempt, not a debate prompt. If the finding doesn't apply to this diff, move past it without ceremony; if it does, fix it in place.

**Aggregate-then-fix posture.** Findings are consumed in-process — the pass's primary deliverable is the resulting commit, **not a document or report**. Apply fixes inline as you walk the diff, carry them through the normal review and verification flow, and commit through the Verify and commit step.

**Stop condition.** If the pass produces no changes, record/mention that the diff was already clean and continue with the Review the implementation step. The pass proceeds even when no commit results — it is advisory within polish, not a blocker.

**DB-claim stop-and-amend interplay.** If the simplify pass uncovers governed DB mutation that the stored claim does not declare, route through the DB-claim stop-and-amend gate documented in `polish/fixes.md` step 7 before continuing.

### Review the implementation (step 6)
Read `.agents/skills/yoke/polish/review.md` and execute it. Examines the worktree diff against `main`, runs the required verification checklist (staleness, blast-radius discovery, residue grep, test co-modification audit, events forensics, file-size awareness), walks the code and test review dimensions for each changed file, and emits a structured review report.

### Apply finishing fixes (step 7)
Read `.agents/skills/yoke/polish/fixes.md` and execute it. Applies targeted fixes within the worktree: AC closure, test co-modification, dead-code deletion, blast-radius cleanup, documentation freshness. Includes the DB-claim stop-and-amend gate when governed DB mutation is discovered mid-polish.

### Verify and commit (steps 8–9)
Read `.agents/skills/yoke/polish/verify-and-commit.md` and execute it. Runs the project's registered test commands (plus any relevant doctor or invariants checks when prompt surfaces were touched), then commits the polish changes with a scoped `git add`. Does not push and does not create a pull request.

### Advance to implemented (steps 10–15)
Read `.agents/skills/yoke/polish/advance.md` and execute it. Re-runs the browser QA and project E2E gates against the polish commit, captures the final summary, advances status to `implemented`, releases the work claim, and emits the final operator output. Stops at `implemented` — usher owns merge and deploy.

### Multi-turn polish session continuity
Polish frequently spans multiple turns when the diff is large or the simplify pass surfaces re-work. For checkpoint notes that successor agents need to resume after compaction, write to the **Progress Log** section on the item — see `AGENTS.md > Progress Log — long-running execution context on items`. Do NOT use `shepherd_log` (epic-only) or the spec/technical_plan fields (intent, not state).
