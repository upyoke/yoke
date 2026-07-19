# Advance — Preflight: Reconciliation, Merge Verification, and Done Redirect

Extracted from `preflight.md`. Covers the implementation reconciliation gate, merge verification gate, and done transition redirect. Read and follow this file when `preflight.md` directs you here.

**Context variables** (inherited from router): `{N}`, `_type`, `_status`, `_target`, `--force` flag

---

## Implementation Reconciliation Gate (step 5-recon, target `implementing` only)

Skip if target is not `implementing`.

This gate runs **before** worktree/environment phases to ensure bypass-created items have required metadata before side effects.

**No epic-child exemption today.** The live schema has no surviving child-item → epic backpointer (`epic_tasks` references the epic, not the child). Epic tasks that reach this gate will run the generic reconciliation path, which is benign for items whose `deployment_flow` is already populated by conduct's plan-handoff. If the exemption becomes mechanically necessary again, add a real relation first and reintroduce the carve-out — do not infer from `epic_task_files` or other indirect signals.

### 1. Deployment flow: recover or block

```bash
_item_flow=$(yoke items get {N} deployment_flow 2>/dev/null)
_item_project=$(yoke items get {N} project 2>/dev/null)
```

If `_item_flow` is empty or null:
- Look up project default from the `deploy_defaults` Project Structure
  family. The helper prints the flow id and exits 0 when configured; it
  exits 1 when no default is set:
 ```bash
 # Source-dev/admin read: populate _default_flow from the deploy_defaults
 # Project Structure family for "$_item_project".
 ```
- If `_default_flow` is non-empty → auto-fill via `items.scalar.update`:

  ```json
  {
    "function": "items.scalar.update",
    "actor": {"session_id": "<this-session>"},
    "target": {"kind": "item", "item_id": {N}},
    "intent": "advance_recover_deployment_flow",
    "payload": {"field": "deployment_flow", "value": "<_default_flow>"}
  }
  ```

  Emit: `Reconciled: deployment_flow auto-filled to '{_default_flow}' from project default.`
- If `_default_flow` is empty → **hard block**:
 > **Blocked:** YOK-{N} has no `deployment_flow` and project '{_item_project}' has no configured `deploy_defaults` entry. Set a flow before advancing to `implementing`. Use the registered item scalar wrapper (`yoke items scalar update YOK-{N} --field deployment_flow --value <flow-name>`) for the item value. Project-wide deploy-default repair is source-dev/admin only today; no registered product CLI wrapper exists for that helper.

 Do NOT update status. Do NOT create worktree. **Stop.**

### 2. GitHub issue: opportunistic sync

```bash
_item_gh=$(yoke items get {N} github_issue 2>/dev/null)
```

If `_item_gh` is empty or null:
- Check canonical project GitHub auth via the resolver — every registered project
  resolve through the same verified `project_github_repo_bindings` surface;
  the control plane mints a short-lived
  installation token and never falls back to a host credential or project
  capability secret.
  The direct resolver probe and issue-sync helper are source-dev/operator-debug
  internals with no registered product CLI wrapper. Lifecycle transitions
  normally sync as a side effect.
- If the resolver raises (missing or suspended installation, missing repo binding, insufficient App permissions, installation-token minting failure, transport failure), emit advisory:
 > **Advisory:** No GitHub issue linked and project GitHub App binding not resolvable. Repair per the github-auth-resolver doctor output, then retry the advance so lifecycle sync side effects can run. Direct issue sync and control-plane App repairs are operator-debug/source-dev only unless a registered wrapper is available for the exact repair.

### 3. Body completeness: advisory only

Check if body is title-only through the shared helper that owns the
slack-bounded heuristic used by frontier blocking and doctor:

```bash
_item_body=$(yoke items get {N} body 2>/dev/null)
_item_title=$(yoke items get {N} title 2>/dev/null)
_body_incomplete=$(
 ITEM_TITLE="$_item_title" ITEM_BODY="$_item_body" python3 - <<'PY'
import os
from yoke_core.domain.idea_body_completeness import is_idea_body_incomplete

print("1" if is_idea_body_incomplete({
    "title": os.environ.get("ITEM_TITLE", ""),
    "body": os.environ.get("ITEM_BODY", ""),
}) else "0")
PY
)
```

If `_body_incomplete` is `1`:
> **Advisory:** YOK-{N} has minimal body content. Cold-start sessions need full context (problem, fix plan, acceptance criteria). Consider updating the body before implementation.

Do not block.

### 4. Pack reuse: advisory only

Skip if `_item_project` is `yoke` (Yoke items already own Pack publishing work).

```bash
_item_spec=$(yoke items get {N} spec 2>/dev/null)
_has_pack_reuse=$(printf '%s' "$_item_spec" | grep -c '## Pack Reuse' 2>/dev/null) || _has_pack_reuse=0
```

If `_item_project` is not `yoke` and `_has_pack_reuse` is 0:
- Also check body:
 ```bash
 _has_pack_reuse_body=$(printf '%s' "$_item_body" | grep -c '## Pack Reuse' 2>/dev/null) || _has_pack_reuse_body=0
 ```
- If both are 0:
 > **Advisory:** YOK-{N} (project={_item_project}) has no `## Pack Reuse` stance. Record whether the change is `project-owned` or a reusable `pack-update` before implementation.

Do not block.

---

After all reconciliation checks pass (or emit advisories), return to router for worktree phase.

## Merge Verification Gate (step 5-merge, target `release` only)

Skip if target is not `release`. **If `--force`:** skip with warning.

```bash
_item_project=$(yoke items get {N} project 2>/dev/null)
if [ -n "$_item_project" ] && [ "$_item_project" != "null" ] && [ "$_item_project" != "" ]; then
 _merge_repo=$(yoke projects get --project "$_item_project" --field repo_path)
else
 _merge_repo=$(git rev-parse --show-toplevel)
fi

# Resolve all branches via the authoritative resolver (handles both single-worktree issues
# and multi-worktree epics). Each branch must be an ancestor of the item's flow gate branch
# before release: the target env's declared deploy branch (environments.settings.git.branch),
# which is main for prod/internal flows and stage for stage flows.
# Resolver is source-dev/admin only; no registered product CLI wrapper exists yet.
_mv_branches=$(python3 -m yoke_core.domain.worktree_item_resolve YOK-{N} --branches 2>/dev/null) || true
```

If `_mv_branches` is empty → advisory warning, proceed.

Check ancestry for each branch (recipe shows `main`, the gate branch for prod/internal flows; substitute the flow's gate branch — e.g. `stage` for a stage-flow item):
```bash
_mv_block=0
while IFS= read -r _wt_branch; do
 [ -z "$_wt_branch" ] && continue
 git -C "$_merge_repo" merge-base --is-ancestor "$_wt_branch" main
 MB_EXIT=$?
 if [ "$MB_EXIT" -ne 0 ]; then
 echo "BLOCK: branch '$_wt_branch' is not an ancestor of main (exit $MB_EXIT)"
 _mv_block=1
 fi
done <<EOF
$_mv_branches
EOF
if [ "$_mv_block" -ne 0 ]; then
 exit 1
fi
```

- All branches exit 0 → all merged, proceed
- Any branch exit 1 → NOT merged, **block** for that branch
- Any branch exit 128 → branch not found, **block** for that branch

## Done Transition Redirect (step 5c, target `done`)

If target is `done`, do NOT update status. Print redirect and **return immediately**:
> Cannot advance to `done` directly. Use `/yoke usher YOK-{N}` to merge and deploy.

---

After all applicable gates pass, return to the router to continue with the next phase.
