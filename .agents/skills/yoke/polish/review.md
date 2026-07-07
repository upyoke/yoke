# Polish — Review The Implementation

Covers polish step 6: examine the worktree diff and review the implementation against ACs, spec, and surrounding context.

**Context variables** (set by earlier phases): `WORKTREE_PATH`, `WORKTREE_PATHS`, plus survey findings from the context phase.

---

## 6. Review The Implementation

Examine the worktree diff against `main` to understand what has already been implemented:

```bash
if [ -n "{WORKTREE_PATH}" ]; then
 git -C "{WORKTREE_PATH}" status --short
 git -C "{WORKTREE_PATH}" diff --stat main...HEAD
 git -C "{WORKTREE_PATH}" diff --name-only main...HEAD
else
 while IFS= read -r _wt; do
  [ -n "$_wt" ] || continue
  printf '\n# %s\n' "$_wt"
  git -C "$_wt" status --short
  git -C "$_wt" diff --stat main...HEAD
  git -C "$_wt" diff --name-only main...HEAD
 done <<'EOF'
{WORKTREE_PATHS}
EOF
fi
```

If a branch has no committed diff against `main` but its worktree is dirty, review the uncommitted changes instead:

```bash
git -C "{lane-path}" diff --stat
git -C "{lane-path}" diff
```

For multi-worktree epics, produce one review section per worktree before writing the item-level synthesis. A finishing gap in any worktree blocks the parent epic from advancing.

Before planning fixes, complete this required verification checklist. **Incorporate all survey findings from the context phase** — codebase drift on main, overlapping active tickets, and recently-done work that affects this branch are first-class review dimensions.

- **Staleness and drift (from the context phase):** If the survey found main-branch changes that conflict with this branch, any overlap with in-flight tickets, or recently-done work that touches the same scope, those findings MUST appear in the review. Any overlap must be resolved: rebase, descope, absorb, dependency-link, or cancel. Do not proceed past review with unresolved overlap.
- **Blast-radius discovery:** Run real grep/search discovery for renamed, removed, or signature-changed behavior. Do not trust the diff or the spec's remembered file list by itself.
- **Residue grep:** After any rename/removal/refactor, run a residue grep for the old identifier/pattern/value and treat non-zero matches as unfinished work.
- **Test co-modification audit:** For every modified script or module, inspect corresponding `test-{module}.sh` files and any tests that reference the changed path. Missing test updates are a first-class bug.
- **Events forensics when debugging:** If a failure or behavior mismatch is unclear, inspect `yoke events query --item {N}` or `yoke events tail --limit 20` before guessing at the cause.
- **Prompt/file-size awareness:** If you touch agent definitions, skill prompts, or large shell/markdown surfaces, measure line counts (`wc -l`) and flag any P-50/readability risk in the review or fix plan.
- **Codebase-reader naming audit:** Check new or renamed files, modules, helpers, tests, docs, commands, events, config keys, symbols, headings, and comments for planning-artifact provenance. Anything named after the ticket, strategy doc, plan, initiative, phase, task, AC/FR label, branch, worktree, or implementation batch must be renamed to current function/purpose/mechanics unless the identifier is itself runtime/domain language.

## File size awareness

Flag authored files over the project line limit as a polish finding. The default limit is 350 lines unless the DB-backed `project-policy.file_line_limit` says otherwise; the `file_line_check` engine backs both the unified agent command (`yoke check file-line --base main`) and the pre-commit hook. If you see oversized authored files, recommend a split. Files that agents can't read in one pass cause context truncation, the root cause of many incomplete implementations (P-50).

For each changed file, review the implementation against the ACs and spec.

Code review dimensions:
- Correctness: Does the code satisfy each AC?
- Completeness — ALL ACs, not just core: Are there ACs not yet addressed by any changed file? Engineers commonly complete the core implementation but skip peripheral ACs (doc updates, test file renames, agent file updates, cleanup of dead code, help text updates). Check EVERY AC checkbox, not just the ones that involve writing new code.
- End-to-end usability: Can the operator actually trigger and experience the result? Is the feature wired into every surface where users encounter it (CLI, UI, help text, error messages)? If the implementation stops at an internal boundary and never connects to the user-facing surface, that's a gap to fix.
- Missing requirements: Would a reasonable person expect outcomes the ACs don't cover? Flag aggressively — error handling, input validation, user-facing messaging, integration with existing workflows, cleanup of replaced state. The question is "would the operator be surprised if this wasn't done," not "did the spec say to do this."
- Verify spec claims before trusting them: If the spec references specific line numbers, function names, column names, or file paths, verify them against the actual code before relying on them. Specs frequently contain phantom references (function names that don't exist, incorrect column names, wrong line numbers, aspirational file counts). When a spec claim doesn't match reality, fix the implementation to match what the code actually needs, not what the spec incorrectly described.
- Codebase-reader naming: Do new or renamed codebase surfaces stand alone for a future repository reader who cannot see the planning artifact? Flag and fix provenance-shaped names copied from tickets, plans, phases, tasks, AC/FR labels, branches, worktrees, or implementation batches.
- Blast radius — grep-verify, don't assume: Are there files outside the diff that reference the old behavior? Run actual grep commands to find callers, importers, docs, configs, scripts, and tests that assume the pre-change state. If the implementation changes a function signature, grep for every caller. If it renames a concept, grep for every reference. If it removes a feature, grep for every mention. Hardcoded file lists in specs are inherently incomplete — always verify with discovery.
- Residue grep: After any rename, removal, or refactoring, run `grep -r OLD_PATTERN .` and confirm zero remaining references to the old name/pattern/value. This is the single most effective check for incomplete blast radius. If the grep returns results, the work isn't done.
- Dead code and dead weight: Does the implementation leave behind anything that only served the old way? Check for: orphaned helper functions, stale imports, unused variables, config keys for removed features, feature flags that are always on/off, migration scripts for already-cleaned-up data, compatibility shims with zero consumers, re-exports and aliases for renamed things, defensive error handling for impossible states, "just in case" fallbacks for scenarios that aren't real. Also check for dead branches in live code — conditionals that always resolve one way, unreachable else/elif/case clauses, and feature flags that are permanently set.
- Efficiency and simplification: Is the code doing something in a roundabout way when a direct approach exists? Flag: unnecessary indirection (wrapper functions that just pass through, abstraction layers with one consumer), redundant computation (same value computed twice, same file read multiple times, same DB query issued repeatedly), unnecessary loops (iterating when a direct lookup or single query would work), multi-step pipelines that could be collapsed into one operation, and over-abstraction (a generic framework built for a single use case). The simplest correct approach should be the default — three clear lines beat a clever one-liner, but twenty lines of ceremony around a two-line operation is waste.
- Documentation freshness: Do comments, docstrings, help text, READMEs, and doc files describe the current state as if the old way never existed? Flag any archaeological layers: "previously this was X," "this used to work like Y," changelog-style amendment instead of clean rewrite. Also flag stale TODOs/FIXMEs referencing completed work.
- Migration simplicity: If the implementation includes migration logic, is it actually needed? Is there live data that needs migrating, or was it already cleaned up? Could a hard cutover replace the graceful migration? Flag migration scripts that operate on empty sets and compatibility code that has zero callers.
- Edge cases: Are error states, empty inputs, and boundary conditions handled?
- Style: Does the code follow project conventions?
- Safety: Are there injection risks, unvalidated inputs, or fragile assumptions?

Test review dimensions:
- Coverage: Is there a test for each AC or behavior change?
- Test co-modification: When ANY script or module is modified, check for and update test-{module}.sh and all test files that reference the modified file. When extracting a shared helper, add the new dependency to ALL test environments that use the caller. This is the most commonly missed class of change.
- Quality: Do tests verify behavior, not just exercise code?
- Isolation: Do tests use their own temp dirs and not share mutable state?
- Dead tests: Are there tests that only exercise removed or replaced behavior? Tests for old code paths, old migration scripts, old compatibility shims, or old feature flags that no longer exist should be deleted, not kept "for safety."
- Test freshness: Do test descriptions and comments describe the current system? Flag tests with stale names or comments referencing the old way.

Emit a structured review:

```
## Polish Review — YOK-{N}

### Implementation Status
- {AC-1}: {covered/partial/missing} — {brief evidence}
- {AC-2}: ...

### Lane Coverage
- {worktree branch/path}: {clean/needs fixes} — {brief evidence}
- ...

### Issues Found
1. {severity}: {description} — {file}:{line}
2. ...

### Finishing Fixes Planned
1. {what to change and why}
2. ...
```
