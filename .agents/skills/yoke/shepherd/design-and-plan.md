# Shepherd: PM Spec Gate, Design Gate, and Architect Transition

Covers the PM spec-writing gate (conditional), the design gate (conditional), and the `refined_idea_to_planning` transition (Architect invocation + Simulator loop). Shepherd is epic-only.

**Be the giant.** We stand on inherited shoulders; leave a leg up for the next agent by making this artifact cold-start complete. The Architect's plan quality determines implementation velocity (P-1). Ensure the dispatch prompt includes all context the Architect needs. The Architect must verify all code references against the live codebase (P-53) — set this expectation in the dispatch.

**Inherited from router:** `MAX_ATTEMPTS`, `MAX_SIMULATOR_FIX_CYCLES`, `_num`, `_type`, `_title`, `_item_status`, `_epic`, `_scholar_context`, `_prior_caveats`, `_transition`, `_attempt`, `_session_id`, `_worker_name`.

**After this step completes:** Return to the router for Boss review (step 5e in `boss-verdict.md`), then steps 6-10 (Shepherd Log, transition continuity, commit, final report).

Read and follow: `design-checks.md` (steps 5a–5b and Designer invocation: PM spec gate, design gate)
Read and follow: `plan-handoff.md` (Architect invocation, DB writes, Simulator loop, Boss handoff)
