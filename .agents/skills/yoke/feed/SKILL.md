---
name: feed
description: "Direct-mode entrypoint -- update stale frontier items, maintain frontier dependency facts, and materialize new work from the SML."
argument-hint: "[--no-new-tickets] [YOK-N ...] [--lane LANE] [--model MODEL]"
---

# /yoke feed

Direct-mode entrypoint for SML-to-idea materialization, stale-ticket refresh, and frontier dependency graph maintenance. Feed reads the Strategic Markdown Layer, the target frontier items, existing dependency edges, and recent codebase changes, then converges on one or more outcomes: leave work in the SML, refresh the graph only, update or sharpen current frontier items, or materialize new tickets.

Feed is the canonical semantic owner of generated frontier-fact maintenance. It writes `source='feed'` dependency rows in `item_dependencies` with human-readable rationale and structured evidence, and it updates stale structured ticket fields when recent landed work changed the frontier's ground truth. It does not own ranking, WIP caps, or claim handling (those belong to the scheduler and charge).

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug not worth a ticket, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Arguments

- `--no-new-tickets` -- Boolean flag. When set, feed runs the same analysis but is forbidden from creating new items, splitting work into new items, or advancing newly created work. If the analysis says new tickets are needed, report "frontier insufficient, new tickets suppressed by flag" instead of pretending sufficiency.
- `YOK-N ...` -- Optional explicit item scope. When present, feed still reads broader frontier/dependency context but deep-reads, stale-ticket updates, and reporting focus on the listed items.
- `--lane LANE` -- Execution lane identity (default: `DARIUS`).
- `--model MODEL` -- Model identifier override.

## Constants

```
REPO_ROOT=$(git rev-parse --show-toplevel)
_project=$(yoke projects checkout-context --field slug)
_project_id=$(yoke projects checkout-context --field id)
_prefix=$(yoke projects checkout-context --field public_item_prefix)
SML_SLUGS="MISSION LANDSCAPE VISION MASTER-PLAN"
```

## Philosophy

**Be the giant.** We stand on inherited shoulders; leave a leg up for the next agent by making this artifact cold-start complete. Feed should turn strategy into backlog items that arrive with enough context to avoid a full rediscovery cycle in idea and shepherd.

**Maximalist intake.** Feed should materialize missing work, not merely sketch vague placeholders. Strategy gaps should become actionable items with clear rationale and blast radius.

**Truthful graph maintenance.** Feed's primary job is ensuring the dependency graph reflects reality, not just adding tickets. A smaller, sharper, more truthful frontier is always preferred over a larger and noisier one. If two items share a hot file, unstable contract, schema surface, hook path, docs surface, test harness, or deployment surface, that relationship must be encoded as a real blocker row rather than left as prose.

**Recent landings redefine the frontier.** Feed must treat recently landed work as first-class input. If a merged change altered a file, contract, hook, schema, doc surface, or test harness that a frontier item assumes, feed updates that item's structured fields before pretending the frontier is still current.

## Steps

### 1. Parse Arguments

Extract `--no-new-tickets`, optional `YOK-N` scope IDs, `--lane`, and `--model` from the user prompt. Apply defaults:

```
_no_new_tickets = true if --no-new-tickets present, false otherwise
_scope_ids = ordered list of explicit YOK-N ids from the prompt (may be empty)
_scope_mode = "scoped" if _scope_ids is non-empty, else "frontier"
_lane = provided --lane value, or "DARIUS"
_model = provided --model value, or "" (empty = use session default)
_mode = "no-new-tickets" if _no_new_tickets, else "default"
```

### 1b. Process Work Claim and Strategy-File Path Claims

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

No path claims are registered — the strategy authority is the per-project Yoke DB `strategy_docs` table (the checkout's `.yoke/strategy/*.md` files are tracked rendered views), and holding the project's FEED process claim is what authorizes any `strategy.doc.replace` writes this run makes while bouncing `yoke strategy ingest` from other sessions.

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

### 2. Emit FeedStarted Event

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

### 3. Stage Dispatch

Read and follow each stage file in order. Each stage builds context for the next.

**Gather:** Read `.agents/skills/yoke/feed/gather.md`
- Resolves scoped vs full-frontier targets, reads the required SML files, deep-reads each target item's structured fields, reads existing dependency edges, and analyzes recent landed commits plus their diff stats
- Produces in-context: target item list with structured artifacts, SML content summary, existing dependency graph, recent landed change summary, and a concrete "tickets that need updating because X landed and changed Y" list

**Decide:** Read `.agents/skills/yoke/feed/decide.md`
- Evaluates recent-landed impact on every target item, identifies stale structured fields that must be updated, and then applies the four decision axes: ground stability, pull-forward safety, frontier sufficiency, definition sufficiency
- Produces a primary decision plus per-area decision outcomes: leave_in_sml, refresh_graph, sharpen_frontier, materialize_new
- If `_no_new_tickets` is true, suppress only the parts that would create new items and say so explicitly

**Materialize:** Read `.agents/skills/yoke/feed/materialize.md`
- Applies stale-ticket updates first via structured-field writes, then creates new tickets via `/yoke idea` when the decision still calls for materialization
- Retains strategic provenance on created items and records which existing tickets were updated, why, and which fields changed

**Reconcile:** Read `.agents/skills/yoke/feed/reconcile.md`
- Adds missing `source='feed'` dependency rows, updates changed rows, removes stale rows
- Preserves operator-authored/manual rows; reports conflicts between generated and manual edges
- Detects stale non-feed edges where the blocker is cancelled or absorbed
- Uses canonical dependency mutation surfaces and tracks exact persisted rows for the final max-safe-parallelism report

**Summarize:** Read `.agents/skills/yoke/feed/summarize.md`
- Reports what landed, what it changed, which tickets were updated, which decision outcome each strategic area got, exact dependency rows persisted, coding waves, merge order, readiness callouts, and residual uncertainty
- Assesses whether the graph is coherent enough for scheduler/charge/merge consumers
- Emits `FeedCompleted` event
