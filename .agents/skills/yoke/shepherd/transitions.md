# Shepherd — resume and execute the binding's edges

## Derive the work

Use `_shepherd_edges` from entry in definition order. Do not reconstruct a
fixed progression. The first edge produces the plan (PM, design, Architect,
Simulator); subsequent edges review the persisted planning artifacts. The
final edge also applies the handoff quality gates. For a one-edge segment,
produce the artifacts and run those gates before its Boss review and handoff.

For each edge retain `_source_stage`, `_target_stage`, and its derived
`_transition` verdict key. `_plan_transition` and `_review_transition` select
artifact roles, never literal stage names.

## Resume

Read `shepherd_verdicts` for ITEM, retaining each verdict's worker and edge
key, then re-read the live item status. Read the Progress Log for execution
context; durable artifacts and stage readback decide what remains.

- A READY/CAVEATS verdict from the edge's Boss review completes that review.
  A SKIPPED artifact worker (for example Designer) does not complete the
  whole edge; finish the Architect, Simulator, and Boss obligations.
- BLOCKED stops with its evidence and recovery. NOT_READY resumes at the next
  attempt; respect `MAX_ATTEMPTS`.
- An accepted edge whose target has not been reached still needs its declared
  lifecycle transition. Do not skip the status write because review passed.
- The first edge may already be at its target because active planning was
  stamped before worker dispatch. That status alone does not prove its review.
- If the live stage is beyond an edge without its qualifying review, stop with
  `shepherd_verdict_missing`, name the edge and missing artifacts, and recover
  the review before continuing. Never jump across unexecuted edges.

## Execute

For every unfinished edge:

1. Reset Scholar context and gather prior caveats.
2. For `_plan_transition`, follow [`design-and-plan.md`](design-and-plan.md).
   For later edges, review existing artifacts without rerunning the Architect
   unless the Boss requests a revision.
3. For `_review_transition`, follow [`planning-gates.md`](planning-gates.md)
   before the Boss review. This also runs for a one-edge segment.
4. Follow [`boss-verdict.md`](boss-verdict.md), including verdict persistence,
   caveat resolution, and the declared lifecycle status write.
5. Follow [`finalize.md`](finalize.md) to re-anchor and auto-continue only while
   another edge remains in this binding.

Completion requires the live item status to equal `_shepherd_through_stage`;
the refreshed item read supplies the next bound skill.
