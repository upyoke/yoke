# Advance — Preflight Gates

> **Orchestrator role:** For implementation-entry advances (`/yoke advance PREFIX-N implementation`), the orchestrator `yoke_core.engines.advance_implementation_entry` calls the same gate helpers (`check_hard_blocks.evaluate_blockers`, `check_ac_presence.evaluate_item`, `path_claim_spec_coverage_gate.evaluate`) and reports the outcome as `AdvancePhaseCompleted{phase="preflight"}`. The prose below is the canonical contract for what each gate enforces — the orchestrator's reference, not a per-call agent recipe. The legacy doc-driven flow below still runs for non-implementing advance targets.

Called by the advance router after identity/lifecycle resolution for
non-implementing transitions. Runs the hard-block dependency gate, AC presence
gate, active reconciliation gate, pinned-skill/generated-task gates, and
the merge verification gate.

**Context variables** (set by router): `{N}`, `_status`, `_target`,
`_current_executor`, `_target_executor`, `_generated_children`,
`_worktree_policy`, `_pinned_definition_json`, `--force` flag

---

## Gate Checks (steps 4-dep through 5a-defer)

Read and follow: `preflight-checks.md`

Covers (in order):
- **Hard-Block Dependency Gate** (step 4-dep): blocks if unresolved dependencies at the activation or integration gate point
- **AC Presence Gate** (step 4-ac): blocks if no checkbox ACs found for implementation-stage targets
- **Spec Coverage Gate** (step 4-cov): applies only when effective File Budget and path claims are both enabled; blocks when `## File Budget` lists paths the active claim does not cover
- **Pinned-Skill Advisory** (step 5): identifies a manual transition into a different registered skill's segment
- **Shepherd Skill Gate** (step 5-shep): applies only when the target path crosses a pinned `shepherd` binding
- **Generated-Task Existence Gate** (step 5-gate): applies only when `generated_children=epic_tasks` and dispatch is at or beyond the `conduct` handoff
- **Generated-Task Completion Gate** (step 5a): applies only when a task-graph parent enters its `usher` or terminal segment
- **Deferred Items Gate** (step 5a-defer): applies only to a generated-task parent entering a pinned terminal stage

## Recovery and Redirect Gates (steps 5-recon through 5c)

Read and follow: `preflight-recovery.md`

Covers (in order):
- **Implementation Reconciliation Gate** (step 5-recon): auto-fills deployment flow, syncs GitHub issue, emits body/template advisories — target `implementing` only
- **Merge Verification Gate** (step 5-merge): checks branch ancestry into main — target `release` only
- **Done Transition Redirect** (step 5c): redirects `done` target to `/yoke usher`

---

## Path Claim Activation Handoff

When target is `implementing`, the pinned definition selects item-level
implementation, and `_effective_path_claims_policy` is not `optional`, the next phase is the
path-claim auto-activation step. The
phase doc lives at `.agents/skills/yoke/advance/activation.md` and the
enforcement owner is `yoke_core.domain.advance_path_claim_activation`.

The phase runs **after** preflight (so the path-claim-required gate has already enforced declaration where it applies) and **before** the worktree phase (so the worktree door-lock check sees `state='active'` rather than `state='planned'`). It auto-flips planned claims to active, surfaces blocked-on-upstream errors, and refuses divergent origin/local refs. Skip when `--no-worktree` is passed — no worktree door-lock will fire and there is nothing to gate against.

After all applicable gates pass, return to the router to continue with the next phase.
