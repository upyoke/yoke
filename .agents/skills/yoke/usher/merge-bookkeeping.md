# Usher — record generated-task landing

Only after all registered lanes have successful merge receipts:

1. Verify every PR/commit and target revision. Engine owns task receipts and
   checkout sync. Unverified sync stops merge_target_sync_failed with exact
   checkout/recovery; preserve other owners' dirty state.
2. Record parent's verified merged_at through items.scalar.update and retain
   every lane identity in item evidence. No parent landing while any lane is
   pending/failed; engine receipts, not an invented timestamp, prove it.
3. Read live pin and immutable definition:

```text
yoke workflows item get PREFIX-N --json
yoke workflows version get {workflow_id} {workflow_version} --json
```

Find the skill_bindings half-open interval containing live status. Already at
declared delivery wait returns to deploy; otherwise walk unique forward
transitions one at a time inside Usher's interval, stopping on entry to the
delivery wait, through lifecycle.transition.execute,
with actual source_status/target_status. Read stage after every write.
No skipped stage, bypassed gate, forced done or early issue close. Ambiguous
edge stops merge_bookkeeping_transition_unresolved with live pin/stage and
workflow repair/operator choice needed. Fresh binding belongs to its skill.

Merge-only records wait and retains parent claim. Gate refusal preserves
stage, reason and recovery; resume there, not replay lane merges. A successful
merge is not successful delivery. After [deploy](deploy.md), pinned terminal gates own
issue close-out. Read actual terminal success before reporting done; otherwise
report landed PRs and remaining bound stage.
