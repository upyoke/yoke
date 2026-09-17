# /yoke polish — the named simplify pass (worktree-diff-scoped)

**This is the first pass of polish.** Run it before the staleness/blast-radius review (the Review the implementation step) and before any test re-run — shrink the diff before re-validating.

The pass reviews the worktree diff against `main` along the reuse, quality, and efficiency axes and future-concept lens from `AGENTS.md`'s `## Simplify — three-axis doctrine` section, applies fixes in place, and continues with the normal polish verification flow.

- **Scope:** implementation-worktree diffs only. For single-worktree items, inspect `git -C "{WORKTREE_PATH}" diff main...HEAD` plus any uncommitted changes. For multi-worktree epics, iterate every path in `WORKTREE_PATHS` and inspect each worktree's diff against `main`. **Do NOT expand to whole-repo cleanup** — that's deferred work, not polish.
- **Run sequentially as a single pass.** Walk the diff once; carry findings across all three axes simultaneously rather than three independent sweeps. Parallel three-sub-agent fan-out is **explicitly deferred to v1**.
- **Reuse:** Does the diff add a new file, helper, template, skill, event, command, or prompt surface that an existing one already covers? Replace with reuse. Does it duplicate an existing constant, type, or helper API? Collapse onto the existing one.
- **Quality:** Is each artifact at the smallest concrete shape that satisfies the request? Remove redundant state, parameter sprawl, copy-paste-with-variation, leaky abstractions, stringly-typed code where types/constants exist, unnecessary wrapper nesting, and unnecessary WHAT comments. Keep only non-obvious WHY comments.
- **Codebase-reader naming:** Are all new or renamed live surfaces named for current function/purpose/mechanics rather than for the work item, plan, phase, task, AC, branch, worktree, or batch that produced them? Rename provenance-shaped surfaces in the polish diff.
- **Efficiency:** Is there redundant computation, repeated file reads, duplicate API calls, N+1 patterns, missed concurrency, hot-path bloat, recurring no-op updates, unnecessary existence pre-checks, unbounded structures, missing cleanup, or overly broad operations? Collapse them. New infrastructure proposed mid-polish must justify itself against existing surfaces.

**Anti-argumentation (verbatim):** **do not argue with the finding, just skip false positives.** A finding is a fix attempt, not a debate prompt. If the finding doesn't apply to this diff, move past it without ceremony; if it does, fix it in place.

**Aggregate-then-fix posture.** Findings are consumed in-process — the pass's primary deliverable is the resulting commit, **not a document or report**. Apply fixes inline as you walk the diff, carry them through the normal review and verification flow, and commit through the Verify and commit step.

**Stop condition.** If the pass produces no changes, record/mention that the diff was already clean and continue with the Review the implementation step. The pass proceeds even when no commit results — it is advisory within polish, not a blocker.

**DB-claim stop-and-amend interplay.** If the simplify pass uncovers governed DB mutation that the stored claim does not declare, route through the DB-claim stop-and-amend gate documented in `polish/fixes.md` step 7 before continuing.


Next: [`review.md`](review.md).
