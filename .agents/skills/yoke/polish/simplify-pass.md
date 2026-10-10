# Polish — First Diff Pass

Run this **first**, before staleness/blast-radius review and any test rerun.
Inspect each registered lane's `git diff main...HEAD` plus uncommitted changes;
stay within those implementation diffs, never whole-repository cleanup.

Walk once as a **single sequential pass**, carrying all axes together:
- **Reuse:** replace duplicate files, helpers, templates, skills, events,
  commands or prompts with existing surfaces; share constants/types/APIs.
- **Quality:** smallest concrete request shape; remove redundant state,
  parameter sprawl, copy variation, leaky/stringly abstractions, wrapper nesting
  and WHAT comments. Preserve non-obvious WHY and current-purpose names.
- **Efficiency:** collapse redundant computation/reads/API calls, N+1 work,
  missed useful concurrency, hot-path bloat, recurring no-op writes, unnecessary
  prechecks, unbounded structures and missing cleanup. Justify new infrastructure.

Apply the doctrine's future-concept and codebase-reader naming lenses across
those three axes.

**do not argue with the finding, just skip false positives.**
Fix applicable findings inline; carry fixes through normal review/verification.
The primary deliverable is the resulting commit, not a report. If no changes
are needed, note that the diff was clean and continue; this pass is advisory.
Do not fan out parallel axis agents.

Undeclared governed DB mutation stops the pass for the amendment in
[fixes.md](fixes.md). Continue with [review.md](review.md).
