# Shepherd — resolve the pinned segment

Preserve supplied ITEM/public ref; resolve its bare items.id from detail.
Project sequence is not item_id. Keep title, original/live status, verified
ambient session identity and exact workflow pin:

```text
yoke workflows item get ITEM --json
yoke workflows version get {workflow_id} {workflow_version} --json
yoke items detail get ITEM --json
```

Missing read: shepherd_pin_unavailable with failed command/recovery, no writes.
A launch mandate requiring first claim takes precedence over this ordinary entry.

Read ordered definition.stages/transitions/skill_bindings/policies. Require one
Shepherd binding, generated_children=epic_tasks and nonempty consecutive edges.
Derive source/through, inclusive ordered segment and every declared edge.
Through-stage is a handoff, outside the working half-open interval.

For each source→target key replace hyphens with underscores and join with
_to_; reject normalized collisions. First key is _plan_transition, last is
_review_transition; one-edge uses the same key for both. Find current bound
skill from live stage. Keep effective_policies.file_budget and path_claims
independent, not posture/raw-policy guesses.

Absent/ambiguous binding, unsupported children, missing edge or key collision:
shepherd_segment_unsupported names pin/condition and corrected published-version
recovery. No built-in substitution or implicit repin. At/past through: no-op;
before entry or another bound skill: report its route, never workflow-id routing.

After ordinary validation, stamp mode/acquire; any refusal stops:

```text
yoke sessions touch --mode shepherd
yoke claims work acquire --item ITEM --reason "Execute pinned Shepherd segment"
```

Next: [transitions.md](transitions.md).
