# Conduct — Entry & Activation (S1–S6f)

Entry and activation stage of the conduct epic flow. Covers argument parsing, environment resolution, gates, epic sync, task auto-resolve, and task activation. **Inherited from router:** `MAX_TESTER_REPROMPTS` and all parsed arguments.

---

### S1. Argument Parsing

Detect `YOK-N` pattern (case-insensitive regex, e.g., `YOK-N`, `yok-7`). Extract the numeric part `{N}`.

Set defaults: `_max_attempts={--max-attempts value, default 5}`, `_no_chain={true if --no-chain flag present, false otherwise}`.

**TodoWrite initialization:** If you have access to TodoWrite, create a checklist of flow steps (activate, engineer, tester, verdict, post-pass). Mark each completed.

**Note:** `_max_attempts` defaults to 5.

### S2. Resolve Environment

```bash
MAIN_ROOT=$(python3 -m yoke_core.domain.worktree paths main)
```

**Resolve project from the item** — read the public project slug via the item getter:
```bash
PROJECT=$(yoke items get YOK-${N} project)
PROJECT=${PROJECT:-yoke}
```

### S2a. Type Gate, Status Gate, and Acceptance Criteria Gate

**Type gate:**
```bash
_item_type=$(yoke items get ${N} type)
```

If `_item_type` is `issue`, halt immediately:
> Error: /yoke conduct does not support issue items. YOK-{N} is type 'issue'.
>
> Issue implementation routes through /yoke advance (main-session inline implementation).
> Run '/yoke advance YOK-{N} implementation' to begin issue implementation.

**Status gate:**
```bash
_item_status=$(yoke items get ${N} status)
```

If the query returns empty, stop: `Item YOK-{N} not found.`

- `planned`: proceed (epic entry point).
- `implementing`: proceed (re-entry, resuming in-progress work).
- `reviewing-implementation`: proceed (re-entry, resuming review cycle).
- `reviewed-implementation`: stop — `YOK-{N} has completed implementation review. Run '/yoke polish YOK-{N}'.`
- `done`: stop — `YOK-{N} is already done.`
- `implemented`: stop — `YOK-{N} is already implemented. Run '/yoke usher YOK-{N}'.`
- `polishing-implementation`: stop — `YOK-{N} is already in polish. Run '/yoke polish YOK-{N}'.`
- `idea`: hard-block — `YOK-{N} is at status 'idea'. Run '/yoke shepherd YOK-{N}'.`
- Otherwise: hard-block — `YOK-{N} is at status '{_item_status}', not 'planned', 'implementing', or 'reviewing-implementation'.`

**Acceptance criteria gate:**
```bash
_item_body=$(yoke items get ${N} body)
```

Search for `- [ ] AC-` lines or unlabeled `- [ ] ` checkboxes under `## Acceptance Criteria`. If none found: hard-block with `YOK-{N} has no acceptance criteria. Run '/yoke shepherd YOK-{N}'.`

### S3. Item Validation

```bash
_type=$(yoke items get ${N} type)
_title=$(yoke items get ${N} title)
```

**Activation dependency check:**

```bash
_dep_output_file=$(mktemp "${TMPDIR:-/tmp}/conduct-hard-blocks.XXXXXX")
if python3 -m yoke_core.domain.check_hard_blocks "YOK-${N}" --gate-point activation >"$_dep_output_file" 2>/dev/null; then
 _dep_exit=0
else
 _dep_exit=$?
fi
_dep_output=$(cat "$_dep_output_file")
rm -f "$_dep_output_file"
```

If `_dep_exit` is non-zero, print dependency list and **HALT**.

### S3b. Register Manual Work Claim

```bash
yoke claims work acquire \
 --item "YOK-${N}"
```

After `claim-work`, verify the session holds an active claim on `YOK-${N}` before
proceeding to S4/S6. This assertion uses the retained operator-debug raw SQL router
because the registered claim acquire surface does not expose a same-row verification
projection. **Never** construct a DB path manually or use worktree-local paths:

```bash
_claim_ok=$(YOKE_SESSION_ID="${YOKE_SESSION_ID}" python3 -m yoke_core.cli.db_router query \
 "SELECT 1 FROM work_claims WHERE session_id='${YOKE_SESSION_ID}' AND item_id=${N} AND released_at IS NULL")
if [ -z "$_claim_ok" ] || [ "$_claim_ok" = "0" ]; then
 echo "HALT: conduct S3b — no active work_claims row found for YOK-${N} under session ${YOKE_SESSION_ID}."
 echo "This session may have been reactivated after a SessionEnd without re-acquiring the claim."
 echo "Recovery: run 'yoke claims work acquire --item YOK-${N}' then retry."
 exit 1
fi
```

**HALT** if the verification returns empty. Do not proceed to S4 or S6 without a confirmed active claim.

### S4. Enter Epic Task Fan-Out Flow

`_type` is guaranteed to be `epic` by the type gate in S2a. Proceed directly to **S6 (Epic Task Fan-Out Flow)**.

---

### S6. Epic Task Fan-Out Flow

This flow runs the epic item through the Engineer/Tester loop with **task-level fan-out**: every chain whose head task is `planned` with satisfied dependencies and a free worktree is enumerated, filtered, and dispatched in parallel within the same conduct invocation. Same-worktree and dependency checks run per candidate so independent chains proceed when their siblings are excluded. Uses the epic preparation and auto-chaining logic from `dispatch-context.md` (steps 5f-epic and 5p).

**Read and follow: `.agents/skills/yoke/conduct/entry-activation-resolution.md`**

This companion file covers S6a through S6f-eph:
- **S6a** — Resolve `_epic_id` from the item.
- **S6b** — Epic sync gate: verify dispatch chains and `github_issue` fields; auto-sync if needed (commits only if tracked changes exist — DB-only sync with no tracked diff is valid and no commit is required).
- **S6c** — Fan-out enumeration: collect every dispatchable head task into `_task_ids`, filtering busy worktrees and unmet dependencies per candidate.
- **S6d** — Same-worktree protection (per-candidate filter).
- **S6e** — Dependency verification (per-candidate filter).
- **S6f** — Activate every task in `_task_ids`: load spec, resolve worktree, record per-task `TASK_BASELINE_${_task_id}`, update status, persist worktree fields. Never stage generated views; if legacy root DB files appear in `data/`, stop and investigate.
- **S6f-eph** — Ephemeral environment lifecycle (E1-E3) for non-yoke projects with `ephemeral-env` capability. Runs once per fan-out batch when the project carries the capability.

---

**Handoff:** Entry and activation are complete. `_task_ids` carries the dispatchable batch (one or more tasks). Read `.agents/skills/yoke/conduct/engineer-tester-loop.md` to continue with the Engineer/Tester dispatch loop (S6g) — the loop branches on batch size: single-task batches go through `engineer-tester-dispatch.md`; multi-task batches consume the parallel pathway in `dispatch-context-dispatch.md` and `dispatch-context-prompts.md` (sections 5g/5i).
