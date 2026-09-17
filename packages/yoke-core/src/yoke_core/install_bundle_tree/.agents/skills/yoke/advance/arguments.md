# /yoke advance — arguments, skip flags, and evidence-only items

Read this when an invocation carries a flag, or when an evidence-only item
needs the empty-branch recovery. The phase steps do not need it.

## Arguments

- `{PREFIX-N}` — Backlog item ID. Accepts prefixed IDs, zero-padded prefixed IDs, or bare numeric IDs.
- `[status]` — Optional target status or advance-target name. If omitted, advances to the next status in the lifecycle. The advance target `implementation` is end-to-end **in the same harness session**: worktree creation is a pure filesystem + DB operation (not a session boundary), the work-claim acquired in preflight is the session's authority over the new worktree, and the same session continues into the implementation sub-skill ([implementing/implementation.md](implementing/implementation.md)) and the review loop until `reviewed-implementation`. No parent-session stop, no claim release on worktree entry, no manual relaunch from the worktree. Stopping at `implementing` and announcing `/yoke polish` (or any later step) as "next" remains the hand-off-to-operator anti-pattern this contract exists to prevent.
- `--env <name>` — Optional. Update the item's `deployed_to` field. Valid environments are resolved per-project from DB tables (`environments` via `sites`, `project_capabilities`). Can be combined with a status advance or used standalone on an already-done item.
- `--no-worktree` — Optional. Skip worktree creation when advancing to `implementing`. The item will remain on the current branch with no isolation. Use this for evidence-only / validation / proof items that intentionally make no repo changes; the done-transition empty-branch guard only applies when a worktree branch exists. A workflow whose pinned `policies.worktrees` is `none` skips lane creation on its own — the flag is neither needed nor meaningful there, and the item may live in a project with no git repository at all.
- `--force` — Optional. Override the file-level collision blocker, generated-task existence/completion gates, or merge verification gate.
- `--skip-polish` — Optional. Operator-asserted fast path across the pinned `polish` skill segment. Dispatches through the advance skill's internal skip handler (`yoke_core.domain.advance_skip`; no registered product CLI wrapper), derives the hops from the binding's `from_stage_id`, `through_stage_id`, ordered stages, and transitions, emits a `SkipHopPerformed` event, and releases the item claim with reason `handoff-to-usher`. Requires the current status to equal that pinned binding's entry stage. Use when the current mission explicitly declares that polish is unnecessary, such as a bounded theme swap whose acceptance criteria require no implementation review. Do NOT infer a skip from the item title, and do NOT pass a target status with this flag — the flag owns the target.
- `--skip-refine` — Optional. Operator-asserted fast path across a pinned `refine` skill segment's gate-free bookkeeping rungs. The internal skip handler (`yoke_core.domain.advance_skip`; no registered product CLI wrapper) validates the current stage against its allowlist and advances to that binding's handoff. It emits a `SkipHopPerformed` event. Use when refine deliberation is unnecessary (low-risk content swaps, copy edits). Do NOT pass a target status with this flag.

Both skip flags:
- Are operator-discoverable via `/yoke advance --help` and via `/yoke do` routing when the mission declares a skip.
- Emit an `ItemStatusChanged` event with `source=skip-polish` or `source=skip-refine` (honest telemetry for Ouroboros).
- Use distinct `YOKE_CLAIM_BYPASS` reasons (`skip-polish`, `skip-refine`) so the pre-implementation safety invariant (claim-bypass only for gate-free bookkeeping rungs) stays intact.
- Refuse invalid current statuses with a clear error. The bypass is operator-asserted, not auto-inferred.

Example invocations:

```bash
# Theme-swap mission declares "SKIP: polish":
/yoke advance PREFIX-N --skip-polish

# Low-risk copy edit declares "SKIP: refine":
/yoke advance PREFIX-N --skip-refine
```

### Evidence-Only Items

Items that require no code changes (validation, proof, guidance updates) should use `--no-worktree` when advancing to `implementing`. This leaves the item without an active implementation lane in `item_worktrees`, so the done-transition engine (`yoke_core.engines.done_transition`) skips the empty-branch guard (exit 8).

**If an evidence-only item was advanced WITHOUT `--no-worktree`** and later hits exit 8 during done-transition or usher, the recovery path is:
1. Complete the caller's rollback to `implemented`; lane release is refused at every other status.
2. Ensure this session holds the item claim: `yoke claims work acquire --item PREFIX-N --reason evidence-only-recovery`.
3. Read the registered implementation-lane path and prove it has no modified tracked or untracked files:

```bash
_wt_path=$(yoke item-worktrees get PREFIX-N \
 --lane-role implementation --field path)
if [ -z "$_wt_path" ] || [ "$_wt_path" = "null" ] || [ ! -d "$_wt_path" ]; then
 echo "Blocked: the registered worktree path cannot be verified."
 exit 1
fi
_wt_dirty=$(git -C "$_wt_path" status --porcelain \
 --untracked-files=all)
_wt_git_rc=$?
if [ "$_wt_git_rc" -ne 0 ] || [ -n "$_wt_dirty" ]; then
 echo "Blocked: preserve or commit every worktree file before lane release."
 exit 1
fi
```

4. Immediately release the attested lane: `yoke item-worktrees release PREFIX-N --all-active --reason evidence-only-recovery`. The adapter repeats the branch and cleanliness checks, and the server requires a post-implementation stage of the pinned workflow with exactly one active implementation lane matching the attestation.
5. Re-run the done-transition or usher command.

The empty-branch guard exists to catch accidental merges of branches with no work. For items that intentionally have no code changes, the guard is a false positive — releasing the active lane records is the canonical recovery.
