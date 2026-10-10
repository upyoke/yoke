# Idea — Claim Conflict Resolution

A draft cannot leave intake with an unrepresented coverage/overlap conflict.
The [claims catalog](../../../../.yoke/docs/reference/db-reference/functions.md)
owns schemas; this phase owns decision order. Idea, Refine and the planning
Architect attest coordination. Runtime Engineer/Tester/Boss/Conduct/Polish/Usher
route collisions back to authoring through the pin/shared handoff, never author
their own compatibility edge.

## 0. Renderer-only shortcut

Only overlap entirely on FAMILY_RENDER_TARGET paths with **disjoint seed
sources** auto-classifies NONE: no dependency or escalation. Mixed hand-authored
paths, shared seeds and non-packet renders (BOARD/events/functions) do not get
this shortcut. agents_render_path_context registers relationships;
HC-path-integrity detects drift. A clean register is the visible signal,
not permission to infer independence for other rendered output.

## 1. Classify before authoring

Read both specs and affected blocks/functions, then gather the evidence packet:
```bash
yoke claims path coordination-decision-build --item PREFIX-N --conflicting-claim <claim-id> --paths <shared-paths>
```

It returns specs, claim state/path metadata and three proposals; it does not
decide. Independent disjoint sections/functions with no logical coupling use
coordination_only. Order-dependent inherited/restructured surfaces require
directional activation evidence. Genuine ambiguity goes to operator decision,
no silently authored edge. Do not hand-author overlap SQL.

## 2. Independent coordination_only

```bash
yoke items dependency add <candidate-ref> <conflicting-ref> idea --gate-point coordination_only --rationale "<shared-paths-disjoint-sections-and-why-independent>"
```

Rationale must be independently verifiable; generic different-concerns text
is insufficient. This attests no lifecycle ordering/path mutex: both claims
plan and activate independently. Normal git conflicts are resolved by governed
merge, not a premature block. Re-register after attestation.

## 3. Directional activation

```bash
yoke items dependency add <candidate-ref> <upstream-ref> idea --gate-point activation --satisfaction fact:merged --rationale "decision=directional. <what-upstream-lands-this-candidate-inherits>"
```

Use the blocker's pinned status (normally status:done) for delivery/closeout,
fact:merged for trunk and fact:deployed:ENV only for a real live-environment need.
Always explicit gate-point; defaulting to activation is not classification.
Re-register without upstream pin so the resolver walks the authoritative graph.
Candidate is blocked until the actual condition; multiple overlapping upstream
holders all must satisfy/release, not just the latest blocked_reason display.
Only the dependent waits. Rationale/doctor review detects missing/stale or
unjustified path-only hard blocks.

## 4. Explicit upstream claim pin, secondary

Only when no edge fits and operator wants that single pin, use the registered
claims.path.register payload's upstream_claim_id. It blocks the candidate but
skips graph traversal; genuine ordering/coordination prefers the graph.
Read exact typed schema before calling. Omitted integration_target uses project
trunk; override only for an intentional non-trunk coordination target.

## 5. Honest no-repo-surface exception

```bash
yoke claims path register --item PREFIX-N --mode exception --exception-reason "<actual-validation-evidence-or-meta-no-surface>"
```
Never turn a required file into exception scope to evade a holder.

## 6. Item blocked flag, last resort

Only when2–5 cannot represent the conflict:
```bash
yoke items block PREFIX-N --reason "<verbatim-refusal-and-needed-upstream-coordination>"
```

Lifecycle status is preserved; never status=blocked. After resolution, registered
unblock then re-register. A synced ordinary idea/refined row with no claim,
no exception and blocked=0 is forbidden; catch-up audit and Refine expose it.
An active holder does not narrow scope in any enabled surface.

## Widen and verify

```bash
yoke claims path widen --claim-id <claim-id> --add-paths <added-paths> --reason "<verified-touch-set-expansion>" --item PREFIX-N
yoke claims path required-gate PREFIX-N
```

Widen existing audit history. Gate pass permits closure; block reads reason,
repairs claim/dependency and reruns. If coverage is narrowed after a real scope
change, use registered amend with named removal/integration target.

Symlink and canonical path are one physical coordination unit; registration
auto-pairs both. The canonical-budget hint is advisory and does not lose
underlying target coverage. Add the canonical budget name when both axes apply.
