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

3. Refused overlap is coordination: report to parent conduct/polish and stop.
   Reconcile dependencies/claims through sanctioned authoring routes, never
   self-author coordination. `path-claim-override` is last resort for irreducible
   live collisions and requires explicit operator approval; never self-authorize.

Apply AGENTS Verification Failure Ownership to test repairs; planned future
claims are not failure waivers or grounds for bypassing reconciliation.
