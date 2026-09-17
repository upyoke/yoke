## Path-claim discipline

Read this before editing a file outside your claimed set. It is the full
coverage contract and every sanctioned widening or escalation route.

## Path-Claim Discipline

**Proactive workflow — widen BEFORE writing, not after the deny.** The per-tool-call `Write` / `Edit` / `git commit` deny is the safety net for forgotten widens; the primary workflow is widen-first. Run these steps at the start of each implementation slice, and again before any sibling-module create/edit that was not in the original slice:

1. **Read your active claim's coverage.** The dispatch prompt's claim block lists the covered paths (`declared_paths` / `declared_targets` from `path-claim-list`); confirm directly with `yoke claims path list --item PREFIX-N --state active` if you need the current state. Treat the listed paths as your write budget.
2. **Widen before the first uncovered write.** Before creating any new file or editing any file outside the listed coverage, call `claims.path.widen` (typed envelope in the claims packet above; canonical CLI is `yoke claims path widen --claim-id N --add-paths PATH1,PATH2,... --reason "<why>" --item PREFIX-N`). The `--claim-id` is required — read it from the `path-claim-list` output above. Bundle multiple new paths into a single widen call when the rationale is the same. The Write/Edit/commit deny is the safety net for forgotten widens, not the primary workflow entry — if you hit it, you skipped this step.
3. **Merges from `main` need the same treatment.** Merges routinely touch files outside the original claim; widen first, then commit the merge.

**`path-claim-override` is last resort.** Reserved for irreducible live collisions and requires **explicit operator approval**. You do not self-authorize the override mid-dispatch. If `claims.path.widen` is itself blocked because another active claim covers the same paths, that is a coordination event — surface it to the parent conduct/polish session and stop. Do not use override to make the obstacle go away.

The same proactive rule applies to verification failures: if a test fix touches a file outside the claim, widen first and add the appropriate dependency edge per AGENTS.md `## Verification Failure Ownership — Hard Rule`. Override only with explicit operator approval.
