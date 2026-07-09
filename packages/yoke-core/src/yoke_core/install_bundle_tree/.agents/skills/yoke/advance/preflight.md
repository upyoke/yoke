# Advance — Preflight Gates

> **Orchestrator role:** For implementation-entry advances (`/yoke advance YOK-N implementation`), the orchestrator [`runtime/api/engines/advance_implementation_entry.py`](../../../../runtime/api/engines/advance_implementation_entry.py) calls the same gate helpers (`check_hard_blocks.evaluate_blockers`, `check_ac_presence.evaluate_item`, `path_claim_spec_coverage_gate.evaluate`) and reports the outcome as `AdvancePhaseCompleted{phase="preflight"}`. The prose below is the canonical contract for what each gate enforces — the orchestrator's reference, not a per-call agent recipe. The legacy doc-driven flow below still runs for non-implementing advance targets.

Called by the advance router after identity/lifecycle resolution for non-implementing transitions. Runs the hard-block dependency gate, AC presence gate, active reconciliation gate, epic-specific gates, and the merge verification gate.

**Context variables** (set by router): `{N}`, `_type`, `_status`, `_target`, `--force` flag, `SCRIPT_DIR`

---

## Gate Checks (steps 4-dep through 5a-defer)

Read and follow: `preflight-checks.md`

Covers (in order):
- **Hard-Block Dependency Gate** (step 4-dep): blocks if unresolved dependencies at the activation or integration gate point
- **AC Presence Gate** (step 4-ac): blocks if no checkbox ACs found for implementation-stage targets
- **Spec Coverage Gate** (step 4-cov): blocks when `## File Budget` lists paths the active path_claim does not cover (catches deferred-coverage drift after upstream blockers release)
- **Epic Advisory** (step 5): informational note for manually advanced epics
- **Shepherd Lifecycle Gate** (step 5-shep, epics only): blocks if missing shepherd's terminal verdict (`planning_to_plan_drafted`; legacy `planned_to_ready` accepted as pre-2026-04-07 compat)
- **Epic Task Existence Gate** (step 5-gate, epics only): blocks if no tasks exist for `planned`/`implementing` targets
- **Epic Task Completion Gate** (step 5a, epics only): blocks if tasks are incomplete for post-implementing targets
- **Deferred Items Gate** (step 5a-defer, epics targeting `done`): blocks if unfiled deferred items

## Recovery and Redirect Gates (steps 5-recon through 5c)

Read and follow: `preflight-recovery.md`

Covers (in order):
- **Implementation Reconciliation Gate** (step 5-recon): auto-fills deployment flow, syncs GitHub issue, emits body/template advisories — target `implementing` only
- **Merge Verification Gate** (step 5-merge): checks branch ancestry into main — target `release` only
- **Done Transition Redirect** (step 5c): redirects `done` target to `/yoke usher`

---

## Path Claim Activation Handoff

When target is `implementing` and the item type is not `epic`, the next phase is the path-claim auto-activation step. The phase doc lives at `.agents/skills/yoke/advance/activation.md` and the enforcement owner is `runtime/api/domain/advance_path_claim_activation.py`.

The phase runs **after** preflight (so the path-claim-required gate has already enforced declaration where it applies) and **before** the worktree phase (so the worktree door-lock check sees `state='active'` rather than `state='planned'`). It auto-flips planned claims to active, surfaces blocked-on-upstream errors, and refuses divergent origin/local refs. Skip when `--no-worktree` is passed — no worktree door-lock will fire and there is nothing to gate against.

After all applicable gates pass, return to the router to continue with the next phase.
