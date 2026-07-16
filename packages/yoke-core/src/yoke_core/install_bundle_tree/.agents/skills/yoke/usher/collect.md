# Usher — Collect & Validate

Steps 1-4c: Parse arguments, collect items, validate status, enforce hard-block dependencies, compute merge order, pre-merge CI check, and block early on dirty target repos.

**Context variables** (set by router): all `_` prefixed arg variables

---

## Step 1: Parse Arguments

Extract from operator input:
- `_ITEMS=""` — space-separated YOK-N numbers
- `_DRY_RUN=0` / `_MERGE_ONLY=0` / `_DEPLOY_ONLY=0`
- `_RESUME=""` — YOK-N if --resume

If `--resume YOK-N`: set `_DEPLOY_ONLY=1`, `_ITEMS="{N}"`.

At least one `YOK-N` (or `--resume YOK-N`) is required. If no items specified → stop with usage message.

## Step 2: Collect Items

Use the specified items directly. No discovery mode — items must be explicitly named.

## Step 3: Status Gate (Hard Block)

Initialize `_ready_items=""`.

For each item, read status. **Standard mode:** `done` → skip silently. `implemented` → append to `_ready_items`. Not `implemented` → hard-reject.

**Deploy-only/resume mode:** `release`, `implemented` → append to `_ready_items`. `done` → skip. Other → hard-reject.

**Deploy-only guard:** For `--deploy-only` (not --resume), verify deploy_stage or post-merge status.

## Step 3b: Integration-Gate Hard-Block Dependency Check

Collect is the pre-merge integration gate. Scope the shared hard-block checker to `--gate-point integration` so the runtime answers the integration-gate question, not the all-gates question. `coordination_only` rows (no path-claim mutex, no merge ordering) and `activation`-only rows (already satisfied at this lifecycle phase) are not merge blockers; only `integration` and `closure` edges to non-terminal upstreams should hold collect.

For each item in `_ready_items`, run the gate-scoped checker:

```bash
for _item in $_ready_items; do
 _dep_output_file=$(mktemp "${TMPDIR:-/tmp}/usher-hard-blocks.XXXXXX")
 if python3 -m yoke_core.domain.check_hard_blocks "YOK-${_item}" --gate-point integration >"$_dep_output_file" 2>/dev/null; then
 _dep_exit=0
 else
 _dep_exit=$?
 fi
 _dep_output=$(cat "$_dep_output_file")
 rm -f "$_dep_output_file"

 if [ "$_dep_exit" -ne 0 ]; then
 # stop with:
 # > **Blocked:** YOK-${_item} has unresolved integration-gate dependencies. All integration blockers must reach `done` before usher can merge or deploy it.
 # and list each BLOCKED|{blocker}|{status}|{title} line for the operator.
 #
 # Additionally, query persisted rationale for each blocker to explain
 # why the integration ordering exists (task 4):
 # > yoke shepherd dependency-list YOK-${_item}
 # Parse the output and for each depends-on row, print:
 # > Blocked by {blocker}: {rationale} (gate: {gate_point}, requires: {satisfaction})
 #
 # Then print:
 # > Inspect the full dependency graph:
 # > yoke shepherd dependency-list YOK-${_item}
 fi
done
```

If any item is blocked, do NOT compute merge order. **Stop.**

## Step 4: Compute Merge Order

After the hard-block gate passes, use the shared dependency-planning kernel (via API) for
integration-gate ordering across `_ready_items`:

```bash
# Query integration-gate candidate ordering via the API service client.
# The planner returns eligible items in topological order and identifies any
# integration-blocked items with structured blocker details.
_plan_json=$(python3 -m yoke_core.api.service_client plan-candidates integration "$_ready_items")
```

If the planning API is unavailable, halt with the returned error. Dependency
ordering is release authority and must not be reconstructed through a second
read path.

Build directed graph, topological sort. Dependencies merge first.

When an item is deferred or reordered due to integration blockers, display the persisted
rationale from the dependency row (task 4). For example:
```
YOK-N deferred: must merge after YOK-N — {rationale from dependency row}
```

**Circular dependency (HARD BLOCK):** If cycle detected → stop.

**Merge order conflict (ADVISORY):** Compare each item branch with its
project's registered `default_branch`; if adjacent items share files, warn
about rebase need.

Present merge order.

## Step 4b: Pre-Merge CI Check (ADVISORY)

Resolve the project + workflow filename from the items being ushered. The
project is read from the first ready item; the workflow filename is
read from the per-project `ci_workflow_file` capability (declared per
project through the capability settings surfaces). When the capability is
absent (e.g. a project that has not yet declared it), the advisory
check skips silently — `HC-projects-ci-workflow-configured` is the
nudge that surfaces the missing configuration.

Resolve these values through typed functions, never a project literal or raw
registry query:

1. Read the first ready item's `project` with `items.get`.
2. Read that project's `github_repo` with `projects.github_binding.status`.
3. Read `workflow_file` from `projects.capability_settings.get` with
   `cap_type="ci_workflow_file"`.
4. Read the project's `default_branch` with `projects.get` and
   `payload.field="default_branch"`.
5. If all four values exist, call `yoke github-actions check-ci REPO WORKFLOW
   --branch DEFAULT_BRANCH --project PROJECT`; otherwise skip this advisory.

The GitHub action resolves the project's verified App binding and uses a
short-lived installation token; no host `gh` binary is needed. The recipe uses
only registered project policy, so it works from any checkout. Run `yoke
github-actions check-ci --help` for flag detail.

If the result reports `"state": "failed"`:
```
GATE [advisory]: The project default-branch CI is failing.
Remediation: Consider fixing default-branch CI first.
```

`state` ∈ `{passed, failed, running, no_runs}` — passing, running, or
no_runs → skip silently. (GitHub Actions `queued` collapses into
`running`.)

## Step 4c: Target Repo Dirty-Tree Check (Hard Block)

Before claims or merge/release transitions, verify that each target repo is free of
user-authored dirty files. Reuse the shared classifier so Yoke-managed bookkeeping
files keep their existing merge-engine semantics:

```bash
for _item in $_ready_items; do
 _item_project=$(yoke items get "$_item" project 2>/dev/null) || true
 _target_repo=$(yoke projects get --project "$_item_project" --field repo_path 2>/dev/null) || true
 if [ -n "$_target_repo" ] && [ -d "$_target_repo" ]; then
 _dirty_report=$(python3 -m yoke_core.domain.classify_dirty_files classify-dirty --repo "$_target_repo" --exclude-worktrees 2>/dev/null) || _dirty_report=""
 _user_dirty=$(printf '%s\n' "$_dirty_report" | sed -n '2p')
 if [ -n "$_user_dirty" ]; then
 echo "BLOCKED: Target repo '$_target_repo' has user-authored uncommitted changes. Commit or stash them before usher."
 printf '%s\n' "$_user_dirty" | tr ' ' '\n' | sed 's/^/ - /'
 exit 1
 fi
 fi
done
```

## Halt recovery: deploy reported failed

If `deploy_stage` shows `<stage>-failed`, check the actual GitHub Actions
conclusion after the work claim is registered below and before retrying.
Yoke's record may disagree with reality when an earlier usher session gave
up before the GH runner picked up the job. If GH succeeded externally, run the
reconcile helper first to align Yoke's records, then resume usher:

```bash
yoke usher reconcile-github YOK-N
# alignment path prints: "Resume usher with: /yoke usher YOK-N --resume"
```

If GH also reports failure, no reconciliation is needed — investigate the GH run logs.
If GH is still running, wait for a terminal state before re-running the helper.

---

Register work claims for collected items. For each `_usher_item` in `{collected_items}`, call `claims.work.acquire`:

```json
{
  "function": "claims.work.acquire",
  "actor": {"session_id": "<this-session>"},
  "target": {"kind": "item", "item_id": <_usher_item>},
  "intent": "usher_collect",
  "payload": {"target": {"kind": "item", "item_id": <_usher_item>}, "reason": "usher_collect"}
}
```

If any response carries `error.code="claim_conflict"`, set `_claim_failed=1` and record the holder session id from the response. After the loop, if `_claim_failed=1`, stop. Do not proceed to plan or merge phases. Print:

```text
Aborting usher — not all claims acquired. Another active session holds one or more items.
Wait for the other session to finish, or ask the operator to release claims manually.
```

After collection and validation, return to router for plan phase.
