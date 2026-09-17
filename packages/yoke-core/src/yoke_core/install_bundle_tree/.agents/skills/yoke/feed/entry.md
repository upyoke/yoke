# /yoke feed steps 1–3 — parse, claim, emit, dispatch

## 1. Parse Arguments

Extract `--no-new-items`, optional `PREFIX-N` scope IDs, `--lane`, and `--model` from the user prompt. Apply defaults:

```
_no_new_items = true if --no-new-items present, false otherwise
_scope_ids = ordered list of explicit PREFIX-N ids from the prompt (may be empty)
_scope_mode = "scoped" if _scope_ids is non-empty, else "frontier"
_lane = provided --lane value, or "DARIUS"
_model = provided --model value, or "" (empty = use session default)
_mode = "no-new-items" if _no_new_items, else "default"
```

## 1b. Process Work Claim and Strategy-File Path Claims

Stamp the session mode so the board's active-session row reflects the live phase (default `wait` misrepresents an active feed). Use the registered session wrapper:

```bash
yoke sessions touch \
 --mode feed
```

Register an exclusive **process** work claim so the session is not auto-ended between interactive checkpoints, and to prevent concurrent feed-or-strategize sessions on the same project. The shared `strategy-control-plane:<project>` conflict group makes any overlap with `/yoke strategize` or another `/yoke feed` reject at acquisition time.

```json
{
  "function": "claims.work.acquire",
  "actor": {"session_id": "<this-session>"},
  "target": {"kind": "process", "process_key": "FEED", "conflict_group": "<$_project>"},
  "intent": "feed_run",
  "payload": {"target": {"kind": "process", "process_key": "FEED", "conflict_group": "<$_project>"}, "reason": "feed_run"}
}
```

If the response carries `error.code="claim_conflict"`, print:

> Another session is already running `/yoke feed` or `/yoke strategize` for this project (shared `strategy-control-plane:<$_project>` conflict group). Only one of those can run at a time per project. Wait for it to finish or end the other session first.

Then abort before `FeedStarted` or any phase dispatch.

No path claims are registered — the strategy authority is the per-project Yoke DB `strategy_docs` table (the checkout's `.yoke/strategy/*.md` files are gitignored local rendered views), and holding the project's FEED process claim is what authorizes any `strategy.doc.replace` writes this run makes while bouncing `yoke strategy ingest` from other sessions.

To release on abort:

```json
{
  "function": "claims.work.release",
  "actor": {"session_id": "<this-session>"},
  "target": {"kind": "claim", "claim_id": <claim_id>},
  "intent": "feed_abort",
  "payload": {"claim_id": <claim_id>, "reason": "released"}
}
```

**Abort invariant:** Every abort path — operator-initiated or error-driven — MUST release the `FEED` process work claim before exiting. The claim is the only lock this loop holds; releasing it reopens the strategy write window for other sessions.

## 2. Emit FeedStarted Event

```bash
yoke events emit \
 --name "FeedStarted" \
 --kind lifecycle \
 --type feed \
 --source-type skill \
 --severity STATUS \
 --outcome started \
 --project "${_project}" \
 --context "{\"lane\":\"${_lane}\",\"model\":\"${_model}\",\"mode\":\"${_mode}\"}"
```

## 3. Stage Dispatch

Read and follow each stage file in order. Each stage builds context for the next.

**Gather:** Read `.agents/skills/yoke/feed/gather.md`
- Resolves scoped vs full-frontier targets, reads the required SML files, deep-reads each target item's structured fields, reads existing dependency edges, and analyzes recent landed commits plus their diff stats
- Produces in-context: target item list with structured artifacts, SML content summary, existing dependency graph, recent landed change summary, and a concrete "work items that need updating because X landed and changed Y" list

**Decide:** Read `.agents/skills/yoke/feed/decide.md`
- Evaluates recent-landed impact on every target item, identifies stale structured fields that must be updated, and then applies the four decision axes: ground stability, pull-forward safety, frontier sufficiency, definition sufficiency
- Produces a primary decision plus per-area decision outcomes: leave_in_sml, refresh_graph, sharpen_frontier, materialize_new
- If `_no_new_items` is true, suppress only the parts that would create new items and say so explicitly

**Materialize:** Read `.agents/skills/yoke/feed/materialize.md`
- Applies stale-work-item updates first via structured-field writes, then creates new work items via `/yoke idea` when the decision still calls for materialization
- Retains strategic provenance on created items and records which existing work items were updated, why, and which fields changed

**Reconcile:** Read `.agents/skills/yoke/feed/reconcile.md`
- Adds missing `source='feed'` dependency rows, updates changed rows, removes stale rows
- Preserves operator-authored/manual rows; reports conflicts between generated and manual edges
- Detects stale non-feed edges where the blocker is cancelled or absorbed
- Uses canonical dependency mutation surfaces and tracks exact persisted rows for the final max-safe-parallelism report

**Summarize:** Read `.agents/skills/yoke/feed/summarize.md`
- Reports what landed, what it changed, which work items were updated, which decision outcome each strategic area got, exact dependency rows persisted, coding waves, merge order, readiness callouts, and residual uncertainty
- Assesses whether the graph is coherent enough for scheduler/charge/merge consumers
- Emits `FeedCompleted` event
