## Path-Claim Discipline

Read before editing outside current coverage. At every implementation slice
and before an uncovered sibling edit/create:

1. Read dispatch declared_paths/declared_targets and current registered claims:
   `yoke claims path list --item PREFIX-N --state active`.
2. Widen **before** uncovered writes, using id from that result:

```text
yoke claims path widen --claim-id N --add-paths PATH1,PATH2,... --reason "<why>" --item PREFIX-N
```

Run --help for planned/directory targets and contract details. Bundle same-reason
paths. Write/Edit/commit refusal is safety net, not the widening entrypoint.
Required uncovered files remain in scope and File Budget; coverage is authority,
not scope. Verification fixes and main merges also require widening first.

3. Refused overlap is coordination: report it to the parent skill and stop.
   The parent (the session holding the work claim) records the decision with
   `yoke claims path coordination-decision-build` and `yoke items dependency add`
   using its own skill as source. Do not author the edge from this subagent.
   When no live holder exists, the parent routes to `/yoke refine`.
   `path-claim-override` is last resort for irreducible live collisions and
   requires explicit operator approval; never self-authorize.

Apply AGENTS Verification Failure Ownership to test repairs; planned future
claims are not failure waivers or grounds for bypassing reconciliation.

Landing releases item-owned path claims with reason `landed`. Delivery retains
the work claim. Before reopened lane edits, register fresh coverage with
`yoke claims path register --item PREFIX-N --paths ... --allow-planned` and
prepare the lane to activate it; released claims cannot be widened or reactivated.
