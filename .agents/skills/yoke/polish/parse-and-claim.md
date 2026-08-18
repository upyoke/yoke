# Polish — Parse And Claim

Covers polish steps 1, 2, and 3: parse the item argument, locate the existing worktree lane set, and activate polish (hard gate).

**Context variables** (consumed by later phases): `ITEM_NUM`,
`ITEM_WORKFLOW_ID`, `ITEM_STATUS`, `ITEM_TITLE`, `WORKTREE_SCOPE`,
`WORKTREE_COUNT`, `WORKTREE_BRANCH`, `WORKTREE_BRANCHES`, `WORKTREE_PATH`,
`WORKTREE_PATHS`, `WORKTREE_EXISTS`, `WORKTREE_MISSING`, `ITEM_PROJECT`,
`REPO_ROOT`.

---

## 1. Parse And Lookup

Resolve the item metadata through the unified DB router.

```bash
MAIN_ROOT=$(git rev-parse --show-toplevel)
ITEM_NUM=$(printf '%s' "{arg}" | sed 's/^[Ss][Uu][Nn]-//; s/^0*//')
ITEM_WORKFLOW_ID=$(yoke items get "$ITEM_NUM" workflow_id 2>/dev/null) || ITEM_WORKFLOW_ID=""
ITEM_STATUS=$(yoke items get "$ITEM_NUM" status 2>/dev/null) || ITEM_STATUS=""
ITEM_TITLE=$(yoke items get "$ITEM_NUM" title 2>/dev/null) || ITEM_TITLE=""
```

If any of those reads come back empty, stop with:
> Item PREFIX-{N} not found.

## 2. Locate The Worktree Lane Set

Use the registered item-worktree adapters so polish resolves the same
repo and definition-selected implementation lane set over https. The
module form `python3 -m yoke_core.domain.worktree resolve` is not an
agent recipe: ambient python3 has no `yoke_core`, and the module opens
local Postgres. Do not collapse those lanes back into `PREFIX-{N}`.

Run these as bare registered commands and parse the JSON in prompt
context — do not capture adapter stdout into a shell variable:

```text
yoke items get PREFIX-N project
yoke item-worktrees list PREFIX-N --json
yoke item-worktrees get PREFIX-N --field path
yoke item-worktrees get PREFIX-N --field branch
```

From that output set:

- `ITEM_PROJECT` — `items get` project slug
- `WORKTREE_COUNT` — number of `worktrees` rows from `item-worktrees list`
- `WORKTREE_PATHS` / `WORKTREE_BRANCHES` — each row's `path` / `branch`
- `WORKTREE_PATH` / `WORKTREE_BRANCH` — `item-worktrees get` for the
  implementation lane when `WORKTREE_COUNT` is 1; leave empty when
  there are multiple lanes and iterate `WORKTREE_PATHS` instead
- `WORKTREE_EXISTS` — `yes` only when every listed path is a directory
- `WORKTREE_MISSING` — listed paths that are not directories
- `WORKTREE_SCOPE` — `item` when one lane, `epic` when more than one
- `REPO_ROOT` — the checkout that owns the first lane (the parent of
  `.worktrees/` when the path contains that segment)

If list or get fails, stop with that command's error. Do not treat a
failed read as zero lanes.

If `WORKTREE_COUNT` is `0` or `WORKTREE_PATHS` is empty, stop:
> **Cannot polish PREFIX-{N}:** No implementation worktree lanes found.
> Issue items need their item worktree; epic items need task-level `worktree_path` rows from conduct.
> Run the appropriate implementation entry command before polish.

If `WORKTREE_EXISTS` is not `yes`, stop:
> **Cannot polish PREFIX-{N}:** One or more recorded worktree lanes are missing.
> Missing lanes:
> `{WORKTREE_MISSING}`
> Re-enter the implementation/conduct flow to recreate or repair the recorded lanes before polish.

All subsequent file operations MUST use absolute paths from `WORKTREE_PATHS`. For a single-lane item, `WORKTREE_PATH` is also set for compatibility with existing snippets. For a multi-lane epic, iterate every non-empty line in `WORKTREE_PATHS`; never substitute `/.../.worktrees/PREFIX-{N}` or reuse one task lane for its siblings.

## 3. Activate Polish — HARD GATE

**This step is mandatory and must execute immediately after worktree validation.** No context gathering, diff review, test execution, or exploration of any kind may happen before this step completes. The claim and status transition are the first executable actions after confirming the item and worktree exist.

**3a. Stamp session mode and claim the item** (claim-before-status ordering). The session stamp uses the registered session wrapper. Then run the work-claim CLI; it acquires the typed claim and touches the session row in the same transaction. The active harness session is resolved from the environment — do not pass `--session-id`.

```bash
yoke sessions touch --mode polish
yoke claims work acquire \
    --item "PREFIX-${ITEM_NUM}" \
    --reason polish_run
```

After `claim-work`, verify the session holds an active claim on `PREFIX-${ITEM_NUM}` before proceeding. Use the canonical DB router — never construct a DB path manually or use worktree-local paths:

```bash
_claim_ok=$(YOKE_SESSION_ID="${YOKE_SESSION_ID}" yoke db read --format lines \
    "SELECT 1 FROM work_claims WHERE session_id='${YOKE_SESSION_ID}' AND item_id=${ITEM_NUM} AND released_at IS NULL")
if [ -z "$_claim_ok" ] || [ "$_claim_ok" = "0" ]; then
    echo "HALT: polish — no active work_claims row for PREFIX-${ITEM_NUM}."
    echo "Recovery: re-run 'yoke claims work acquire --item PREFIX-${ITEM_NUM} --reason polish_run'."
    exit 1
fi
```

If `claim-work` reports `error.code="claim_conflict"` (item held by another live session), **stop immediately**. Do not proceed to context gathering or review.

Function-call equivalent (for dispatch-surface callers — the CLI above builds this envelope internally):

```jsonc
{
  "function": "claims.work.acquire",
  "actor": {"session_id": "<this-session>"},
  "target": {"kind": "item", "item_id": $ITEM_NUM},
  "payload": {"target": {"kind": "item", "item_id": $ITEM_NUM}, "reason": "polish_run"}
}
```

**3b. Transition to polishing-implementation** (when entry status is `reviewed-implementation`). Use `/yoke advance` so the canonical advance skill runs the gate and emits the matching event:

```bash
/yoke advance "PREFIX-${ITEM_NUM}" polishing-implementation
```

Update `ITEM_STATUS="polishing-implementation"` in your local shell context after the advance returns success.

Function-call equivalent (for dispatch-surface callers — `/yoke advance` builds this envelope internally):

```jsonc
{
  "function": "lifecycle.transition.execute",
  "actor": {"session_id": "<this-session>"},
  "target": {"kind": "item", "item_id": $ITEM_NUM},
  "intent": "enter_polish",
  "payload": {"source_status": "reviewed-implementation", "target_status": "polishing-implementation"}
}
```

**3c. Verification checkpoint:** After this step, `ITEM_STATUS` must be `polishing-implementation` and the session must hold the work claim. If either condition is not met, stop and surface the error. Only proceed to the context phase (`.agents/skills/yoke/polish/context.md`) after both are confirmed.
