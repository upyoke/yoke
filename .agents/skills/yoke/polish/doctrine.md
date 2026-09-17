# /yoke polish — doctrine and the simplify anchor

Read this before the simplify pass and the implementation review. It is
what the passes look for; the entrypoint carries only what binds from the
first action.

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

**Be the giant.** We stand on inherited shoulders; leave a leg up for the next agent. Your polished code and commit messages are the current handoff: clean commits, well-named functions, and accurate comments. Do not restate the implementation transcript. Sloppy commits with "fix stuff" messages force the next person to re-investigate.

**No such thing as "agent error."** When the review reveals that the Engineer produced incomplete or incorrect code, never frame this as "the engineer made a mistake." The cause is always systemic: the task spec was ambiguous, an interface contract was incomplete, a file was too large for the agent to read fully (P-50: files past agent read limits cause context corruption), or the dispatch context was missing critical paths. Frame every issue as what the SYSTEM should change to prevent it. Fix the code, but also note the systemic cause for the review report.

**Events table for debugging.** When investigating unexpected behavior or test failures during polish, query the events table for recent telemetry: `yoke events tail --limit 20` or `yoke events anomalies --since "4 hours ago"`. Anomaly flags (nonzero_exit, benign_failure, generated_view_write) and tool call timing reveal what happened during the Engineer's session and whether the failure was systemic or code-specific.

**Think, don't just check.** The review dimensions in this skill are a starting point, not a ceiling. Before and after working through the checklist, step back and think about the implementation as a whole: Does this branch actually deliver what the work item intended? Would the operator be satisfied using the result end-to-end? What would a thoughtful senior engineer notice that the checklist doesn't cover? Work top-down (from the work item's purpose to the code) as well as bottom-up (from each file's diff to the overall picture). The checklist catches known failure modes; your judgment catches everything else. If something feels wrong, wasteful, incomplete, or fragile but doesn't match a specific review dimension, fix it or flag it anyway.

**Codebase-reader naming.** Assume future readers of the codebase will NOT have the ephemeral planning artifacts this branch was written from. During polish, rewrite any new or renamed file, module, helper, test, doc, command, event, config key, symbol, heading, or comment that explains itself by pointing at a work item, strategy doc, plan, initiative, phase, task, AC/FR label, branch, worktree, or implementation batch. Polished code describes current function, purpose, mechanics, and domain role to a repository reader.

## Simplify Anchor (reuse / quality / efficiency)

The polish Philosophy above (`Clean-slate after every change`, `Dead weight has zero tolerance`, `Simplest migration wins`) IS the simplify three-axis vocabulary at the polish stage. The shared definition, including the future-concept pull-forward lens, lives in `AGENTS.md`'s `## Simplify — three-axis doctrine` section; polish anchors that vocabulary under explicit headings:

- **Reuse** — clean-slate after every change; rewrite to describe the present rather than amending; remove compatibility shims, re-exports, and aliases nothing imports.
- **Quality** — dead weight has zero tolerance; orphaned helpers, dead config, dead tests, defensive code for impossible states all get deleted; only non-obvious WHY comments remain; names and current-state docs describe current function/purpose/mechanics rather than planning provenance.
- **Efficiency** — simplest migration wins; default to hard cutover; flag unnecessary indirection, redundant computation, multi-step pipelines that could collapse into one operation; justify infrastructure against existing surfaces.
- **Future-concept lens** — if the diff touches actors, sessions, heartbeats, ownership, leases, claims, approvals, overrides, evidence, run records, journals, packets, locks, or shared-state coordination, treat the surface as an end-state v0 or require a deletion / absorption target.

Polish runs the three axes as a **single sequential pass** at the start of the polish flow (see the Named simplify pass below) — **NOT** parallel three-sub-agent fan-out. v0 keeps the pass sequential by design; parallel-fan-out is explicitly deferred to v1.

