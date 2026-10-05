# Conduct — Entry & Activation (S1–S6f)

Entry and activation stage of the conduct epic flow. Covers argument parsing, environment resolution, gates, epic sync, task auto-resolve, and task activation. **Inherited from router:** `MAX_TESTER_REPROMPTS` and all parsed arguments.

---

### S1. Argument Parsing

Detect `PREFIX-N` pattern (case-insensitive regex, e.g., `PREFIX-N`, `yok-7`).
Keep that token as the public item ref for every CLI item argument. Do not
treat the numeric tail as `items.id`.

Set defaults: `_max_attempts={--max-attempts value, default 5}`, `_no_chain={true if --no-chain flag present, false otherwise}`.

**TodoWrite initialization:** If you have access to TodoWrite, create a checklist of flow steps (activate, engineer, tester, verdict, post-pass). Mark each completed.

**Note:** `_max_attempts` defaults to 5.

### S2. Resolve Environment

```bash
MAIN_ROOT=$(python3 -m yoke_core.domain.worktree paths main)
```

**Resolve project from the item** — read the public project slug via the item getter:
```bash
PROJECT=$(yoke items get PREFIX-${N} project)
if [ -z "$PROJECT" ]; then
  echo "project_required: item PREFIX-${N} has no project attribution."
  exit 1
fi
```

### S2a. Workflow Binding, Status, and Acceptance Criteria Gates

**Workflow binding and status gate:** Re-read
`yoke workflows item get PREFIX-N --json` and apply the gate in
[`entry-gates.md`](entry-gates.md) gate 1 against the exact pinned definition.
Retain `CONDUCT_BINDING`, the definition, and its live stage. Proceed only
while the stage is inside that binding's half-open segment and `skill_id`
is `conduct`; otherwise use its named refusal and rendered recovery.
Do not maintain a second workflow-name or status allowlist here.

**Acceptance criteria gate:**
```bash
_item_body=$(yoke items get ${N} body)
```

Search for `- [ ] AC-` lines or unlabeled `- [ ] ` checkboxes under `## Acceptance Criteria`. If none found: hard-block with `PREFIX-{N} has no acceptance criteria. Run '/yoke shepherd PREFIX-{N}'.`

### S3. Item Validation

```bash
_title=$(yoke items get ${N} title)
```

**Activation dependency check:**

```bash
_dep_output_file=$(mktemp "${TMPDIR:-/tmp}/conduct-hard-blocks.XXXXXX")
if python3 -m yoke_core.domain.check_hard_blocks "PREFIX-${N}" --gate-point activation >"$_dep_output_file" 2>/dev/null; then
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
 --item "PREFIX-${N}"
```

After `claim-work`, verify the session holds an active claim on `PREFIX-${N}` before
proceeding to S4/S6. This assertion uses the retained operator-debug raw SQL router
because the registered claim acquire surface does not expose a same-row verification
projection. **Never** construct a DB path manually or use worktree-local paths:

```bash
_claim_ok=$(YOKE_SESSION_ID="${YOKE_SESSION_ID}" yoke db read --format lines \
 "SELECT 1 FROM work_claims WHERE session_id='${YOKE_SESSION_ID}' AND item_id=${N} AND released_at IS NULL")
if [ -z "$_claim_ok" ] || [ "$_claim_ok" = "0" ]; then
 echo "HALT: conduct S3b — no active work_claims row found for PREFIX-${N} under session ${YOKE_SESSION_ID}."
 echo "This session may have been reactivated after a SessionEnd without re-acquiring the claim."
 echo "Recovery: run 'yoke claims work acquire --item PREFIX-${N}' then retry."
 exit 1
fi
```

**HALT** if the verification returns empty. Do not proceed to S4 or S6 without a confirmed active claim.

### S4. Enter Epic Task Fan-Out Flow

S2a established that `conduct` owns the live stage. Use the retained pinned
`policies.generated_children` and `policies.worktrees` to resolve the
generated task graph and its registered lanes, then proceed to **S6 (Epic
Task Fan-Out Flow)**. The epic-task surfaces name the task graph; they do
not require the parent workflow to be named `epic`.

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
- **S6f-eph** — Ephemeral environment lifecycle (E1-E3) for any non-empty project with `ephemeral-env` capability. Runs once per fan-out batch when the project carries the capability.

---

**Handoff:** Entry and activation are complete. `_task_ids` carries the dispatchable batch (one or more tasks). Read `.agents/skills/yoke/conduct/engineer-tester-loop.md` to continue with the Engineer/Tester dispatch loop (S6g) — the loop branches on batch size: single-task batches go through `engineer-tester-dispatch.md`; multi-task batches consume the parallel pathway in `dispatch-context-dispatch.md` and `dispatch-context-prompts.md` (sections 5g/5i).
