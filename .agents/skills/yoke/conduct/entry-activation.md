# Conduct — claim, survey and activation

Apply [entry-gates.md](entry-gates.md) before mutation. Keep the complete public
ref; its numeric tail is project_sequence, never items.id. Resolve the item's
project and owning main checkout through the retained source-dev resolver:

```text
yoke items get PREFIX-N project
python3 -m yoke_core.domain.worktree paths main
```

Missing project halts project_required. MAIN_ROOT is control-plane/branch-ref
access; registered task paths are execution lanes, never local DB authority.

### S3b. Acquire and verify work ownership

The launch handoff may already hold this claim; same-session acquisition is
idempotent. No manual registration or session-presence precondition.

```text
yoke claims work acquire --item PREFIX-N --reason "Conduct entry"
yoke sessions identity --json
yoke db read --format lines "SELECT 1 FROM work_claims WHERE session_id='{SESSION_ID}' AND target_kind='item' AND scope::jsonb->>'item_id'=(SELECT item_id::text FROM item_refs WHERE public_ref='PREFIX-N') AND released_at IS NULL"
```

This diagnostic verifies the active same-session work_claims row. HALT if empty
or the read fails; recover with yoke claims work acquire and verify again.
Never construct a DB path. Registered acquisition owns the claim boundary.

### Epic Task Fan-Out Flow

After claim/read/minimal survey, immediately recover or create registered lanes
through [entry-activation-resolution.md](entry-activation-resolution.md).
Pinned generated_children/worktrees policies own graph/lane shape, not the
workflow name. Auto-sync may be DB-only with no tracked diff; valid success
needs no git commit. Never stage generated BOARD; legacy root DB files stop
for investigation. Ordinary activation remains scoped --gate-point activation.

Resolution returns _task_ids and each _worktree_branch_${_task_id}/
_worktree_path_${_task_id}; no second item's lane is borrowed. Same session
continues through [engineer-tester-loop.md](engineer-tester-loop.md): one task
uses the single dispatch; multiple tasks use dispatch-context-dispatch.md and
dispatch-context-prompts.md. No parent stop, relaunch or fabricated envelope.
