# /yoke strategize steps 1–3 — parse, claim, emit, dispatch

## 1. Parse Arguments

Extract `--lane` and `--model` from the user prompt. Apply defaults:

```
_lane = provided --lane value, or "DARIUS"
_model = provided --model value, or "" (empty = use session default)
```

## 1b. Process Work Claim

Stamp the session mode so the board's active-session row reflects the live phase (default `wait` misrepresents an active strategize). Use the registered session wrapper:

```bash
yoke sessions touch \
 --mode strategize
```

Register an exclusive **process** work claim so the session is not auto-ended between interactive checkpoints, and to prevent concurrent strategize-or-feed sessions on the same project (the shared `strategy-control-plane:<project>` conflict group makes any overlap reject at acquisition time; other projects strategize concurrently). The claim is a pure process lock: holding it is also what authorizes this session's `strategy.doc.replace` writes on this project (the server bounces replace without the TARGET project's claim), and a live claim makes `yoke strategy ingest` from other sessions wait. Operator/debug adapter: `yoke claims work acquire --process STRATEGIZE`.

```json
{
  "function": "claims.work.acquire",
  "actor": {"session_id": "<this-session>"},
  "target": {"kind": "process", "process_key": "STRATEGIZE", "conflict_group": "<$_project>"},
  "intent": "strategize_run",
  "payload": {"target": {"kind": "process", "process_key": "STRATEGIZE", "conflict_group": "<$_project>"}, "reason": "strategize_run"}
}
```

If the response carries `error.code="claim_conflict"`, print:

> Another session is already running `/yoke strategize` or `/yoke feed` for this project (shared `strategy-control-plane:<$_project>` conflict group). Only one of those can run at a time per project. Wait for it to finish or end the other session first.

Then abort before `StrategizeStarted` or any phase dispatch. Do NOT emit `StrategizeStarted`. Do NOT read any phase files. **Stop immediately.**

No path claims are registered — the strategy authority is the DB, and the write window is authorized solely by the `STRATEGIZE` process work-claim acquired above. The rendered `.yoke/strategy/*.md` views are gitignored local caches that are never committed, so there is no commit to authorize and no cross-session path coordination to claim.

To release on abort:

```json
{
  "function": "claims.work.release",
  "actor": {"session_id": "<this-session>"},
  "target": {"kind": "claim", "claim_id": <claim_id>},
  "intent": "strategize_abort",
  "payload": {"claim_id": <claim_id>, "reason": "released"}
}
```

Operator/debug adapter: `yoke claims work release --claim-id <claim_id> --reason "strategize abort"` (the unified CLI takes `--claim-id` / `--item` / `--epic-id`+`--task-num` / `--all-mine`, not `--process`; resolve the STRATEGIZE work-claim id first via `yoke claims work holder-list` or by reading the process-claim row).

## 2. Emit StrategizeStarted Event

```bash
yoke events emit \
 --name "StrategizeStarted" \
 --kind lifecycle \
 --type strategize \
 --source-type skill \
 --severity STATUS \
 --outcome started \
 --project "${_project}" \
 --context "{\"lane\":\"${_lane}\",\"model\":\"${_model}\"}"
```

## 3. Phase Dispatch

Read and follow each phase file in order. Each phase builds context for the next. The operator may halt the pipeline at any checkpoint.

**Abort invariant:** Every abort path — whether operator-initiated or error-driven — MUST release the `STRATEGIZE` process work claim before exiting. Call `claims.work.release` with `target.kind="process"`, `process_key="STRATEGIZE"`, and `conflict_group="<$_project>"`. The claim is the only lock this loop holds; releasing it reopens the write window (replace stops authorizing, and `yoke strategy ingest` from other sessions stops bouncing). Each phase file's abort instructions include the `claims.work.release` call.

**State Refresh:** Read `.agents/skills/yoke/strategize/refresh.md`
- Delta bounding, state gathering, Checkpoint 0 (state refresh confirmation), Checkpoint 1 (problem framing)
- Emits `SMLRefreshCompleted`

**Research:** Read `.agents/skills/yoke/strategize/research.md`
- Source-backed landscape research, Checkpoint 2 (normative filter)
- Also runs a LANDSCAPE.md editorial-pressure pass that flags overgrown or dense sections, duplicate observations, table-stakes entries, stale claims, and clusters of recent developments that should be summarized rather than enumerated
- Produces landscape findings and operator-filter results for `propose.md`

**Propose:** Read `.agents/skills/yoke/strategize/propose.md`
- Draft SML changes, Checkpoint 3 (SML change approval)
- Applies LANDSCAPE.md editorial discipline on top of the minimal-diff principle: weave new signal into existing sections first, consolidate before adding, retire stale or table-stakes observations, and justify any net-new bullet or paragraph
- Emits `SMLChangeProposed` for each proposed change batch

**Approve:** Read `.agents/skills/yoke/strategize/approve.md`
- Apply approved SML changes to the DB (the durable record; rendered views are gitignored and not committed), then run Checkpoint 4 (frontier implication check) and Checkpoint 5 (tradeoff resolution if needed)
- Emits `SMLChangeApproved` for approved changes

**Finalize:** Read `.agents/skills/yoke/strategize/finalize.md`
- Record comprehensive audit trail and print the session summary
- Emits `StrategizeCompleted`
