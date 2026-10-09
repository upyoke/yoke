# Strategize — source-backed research and checkpoint 2

Use confirmed state/framing/delta. Separate objective observations,
interpretations and proposed actions; cite evidence for factual claims.

## Analyze every SML document

- Factual drift: completed work unreflected, stale dates/boundaries, changed
  competitive/environment claims, completed/newly-unblocked frontier items.
  Record file/section/current claim/observed reality and confidence:
  high for clear facts, medium when interpretation is needed.
- Missing context: landed capabilities/patterns, strategic shifts, completed
  boundaries, new dependencies/constraints.
- Future-concept pull-forward: current/landed actors, sessions, heartbeats,
  ownership, leases, claims, approvals, overrides, evidence, run records,
  journals, packets, route-around facts, resource locks or coordination may
  already be v0 of a later concept. Flag unreflected v0 and temporary local
  workarounds lacking a deletion/absorption target. Record current surface,
  later concept, move (pull forward/consume existing primitive/declare deletion
  target) and affected SML section. Sequencing boundaries are not architecture.
- Contradictions: Mission is the hardest constraint; compare Vision/priorities,
  Landscape/live state, overlapping/gapped plan boundaries.
- Trace a specific operator question across relevant docs; general coherence
  needs no extra problem-specific pass.

## Deterministic plan validation

```sh
yoke strategy master-plan-check --plan-path "<repo-root>/.yoke/strategy/MASTER-PLAN.md"
```

Read-only validator uses the rendered cache. If render-staleness is flagged,
first `yoke strategy render --target-root <repo-root>`; edits still go through
proposal/approval and registered DB writes.

Carry EVERY ordered-frontier/prerequisite contradiction (earlier/later refs,
statuses and rationale) as high-confidence drift. Dense prerequisite prose
with >=3 refs is a medium advisory, not an inferred pair. Missing Backlog By
Generation, exceptional status or no live row are soft notes. A no-contradiction
result covers only those two axes; still perform the other narrative checks.

## LANDSCAPE editorial pressure — always

Legibility/density matter even when facts are correct. Flag overgrown/dense
sections, duplicate observations, table-stakes, stale/superseded claims and
related developments that need synthesis. Record section/brief excerpt or
bullet count/editorial move/rationale: weave, consolidate, retire, summarize,
rewrite. Focus problem-related sections; note unrelated pressure briefly.
Preserve genuine signal through synthesis.

Compile counted category tables: Factual Drift, Missing Context, Future-Concept
Pull-Forward, Contradictions, LANDSCAPE Editorial Pressure, and applicable
Problem-Specific Findings.

## Checkpoint 2 — normative filter

Present numbered findings in ordinary chat, each with Fact / Interpretation /
Proposed Action (future concepts also Required Move). Ask which matter:
- All: `cp2:all`, carry every finding.
- Subset by number/category/description: confirm ambiguity in chat, retain only
  selected findings, `cp2:filtered_{kept}_of_{total}`.
- Reframe: clarify once if needed, redo analysis with new framing and re-enter;
  previous round is superseded, record only final outcome.
- Abort: entry release contract, stop.

Carry `## Landscape Analysis` and `## Operator Filter Results` with selected
count/categories/numbered facts, interpretations and actions.
