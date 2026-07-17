# Refine — Idea-Entry Readiness Repair

Sibling phase doc for [`SKILL.md`](SKILL.md) step 1b. Owns the
classification-and-repair branch of the pre-handoff
`idea_readiness_check`. The dispatch lives in `SKILL.md`; the routing
table, command shapes, and operator semantics live here so the cap-near
SKILL stays small.

## Why this exists

`idea_readiness_check` emits a small set of issue codes. They are not
all equivalent — some are mechanical (a recorded line count drifted
from the live file) and some name a real design decision (an unresolved
function reference, a sibling-plan gap above the 330-line threshold,
a mismatch between the File Budget and the path-claim's coverage).

Refine used to release the work claim and exit on **any** non-empty
readiness output. That conflated "the spec needs human judgement" with
"the spec recorded a stale numeric count in its File Budget" — and
``/yoke do`` then treated the released claim as a completed handler,
re-offered, and often re-selected a different item. The mechanical
case is a self-contained repair that should not require the operator
to come back.

The classifier and helper here let refine repair stale-count drift in
place, re-run the readiness check, and continue the same routed
handler without releasing the claim or surrendering the chain step.

## The classifier

`yoke_core.domain.idea_readiness_repair.classify_readiness_issues(issues)`
buckets a readiness-check `issues` list into four classes:

| Class | When | Refine entry routing |
|---|---|---|
| `pass` | empty issues list | Continue refine; no repair needed. |
| `pure_stale_count` | every issue is `STALE_LINE_COUNT` | Invoke the repair helper, re-run, continue on pass; block on refusal. |
| `mixed_stale_count` | at least one recoverable claim-coverage code is present (`FILE_BUDGET_NOT_IN_CLAIM` / `CLAIM_NOT_IN_FILE_BUDGET` / `cross_item_overlap`), and every issue code is claim-coverage or optional `STALE_LINE_COUNT` | Dispatch to the internal claim-coverage helper for `FILE_BUDGET_NOT_IN_CLAIM` / `CLAIM_NOT_IN_FILE_BUDGET` — it auto-widens / auto-narrows / refuses ambiguous shapes. `cross_item_overlap` is agent-attested (see `## Cross-item overlap repair` below); the agent classifies and authors the matching `item_dependencies` row, then refine re-runs `idea_readiness_check` to confirm pass. On refusal or escalation, continue into refine; step 4b's path-claim re-check and step 5/6 critique cover the remainder. The final readiness rerun before status mutation catches anything still unresolved. |
| `unrecoverable` | anything else (unresolved refs, missing sibling plan, or a code outside the recoverable set) | Release the claim with reason `readiness-check-blocked` and exit 1 — same terminal behavior refine had before. |

The classifier is a pure function and is unit-tested in
[`runtime/api/domain/test_idea_readiness_repair.py`](../../../../runtime/api/domain/test_idea_readiness_repair.py).
Refine MUST classify before deciding whether to release the claim;
the order matters because release-then-classify burns the chain step
even on the recoverable branch.

## The repair helper

`yoke_core.domain.idea_readiness_repair.attempt_stale_count_repair`
is the Python entry point. It:

1. Re-checks the classification (refuses anything other than
   `pure_stale_count`).
2. Reads the spec text via the canonical structured-field read path.
3. For each `STALE_LINE_COUNT` issue, recomputes the live count from
   the worktree, refusing the repair when:
   - the named file does not exist,
   - the recorded count is missing or non-numeric,
   - the recomputed count is `>= SIBLING_REQUIRED_THRESHOLD` (330)
     and the spec lacks a sibling-module plan, or
   - the targeted ``path = N`` substring is missing or appears more
     than once in the spec (ambiguous match).
4. Writes the updated spec through `execute_structured_write` —
   inheriting the empty/shrinkage/freeze guards. A guarded refusal
   surfaces as `outcome.error` and is **not** silently bypassed.
5. Re-runs `idea_readiness_check` against the live DB and reports
   `rerun_verdict=pass|block` plus the residual `rerun_issues`.
6. Emits `IdeaReadinessAutofixApplied` with `item_id`, `field`,
   the repaired paths, and the post-repair verdict (best-effort —
   audit failure does not fail the repair).

The registered CLI surface is
``yoke readiness repair-stale-count --item YOK-N``; it runs the
check, classifies, attempts the repair when applicable, re-runs, and
prints the structured payload.

## Cross-item overlap repair — classify before authoring

Structural gate: `yoke_core.domain.idea_readiness_repair_cross_item_overlap.probe_cross_item_overlap` runs inside `idea_readiness_check.run_all_checks` and emits a `cross_item_overlap` readiness issue per unresolved cluster. The classifier routes that code through `CLASS_MIXED_STALE_COUNT`, so refine-entry sees it on the recoverable branch and stays in the refine flow rather than releasing the claim. The probe self-silences when the cluster is already attested (authored `coordination_only` row, candidate-as-DEPENDENT of a non-coordination edge, candidate-as-BLOCKER reverse case, or active operator override). When readiness surfaces this code, refine MUST classify the overlap before authoring any dependency row. Refine runs without the operator in the loop, so the helper output and both items' specs are the only evidence the agent has. Default to the narrowest edge that fits — `coordination_only` attests the overlap is compatible without gating lifecycle or path-claim activation, so most file-level overlaps in this codebase belong there. `activation` is a heavier hammer and must be backed by explicit directional evidence.

The readiness issue's `context.recovery_command` is a ready-to-paste invocation of the evidence helper; copy it verbatim.

1. Invoke
   ``yoke claims path coordination-decision-build
   --item YOK-N --conflicting-claim M --paths <shared>``
   (or run the recovery command emitted on the issue).
2. Read the returned context packet (both specs, conflicting claim
   state, three suggested commands — one per decision option).
3. Decide from the evidence:
   - **Independent edits** (different sections / no logical coupling) →
     author ``coordination_only`` with rationale naming the shared paths
     and the disjoint subsections each ticket edits.
   - **Order-dependent edits** (candidate inherits or restructures what
     upstream lands) → author explicit ``--gate-point activation`` with
     directional rationale (`decision=directional, ...`).
   - **Genuinely ambiguous** → release the claim with reason
     ``coordination-decision-escalated`` and exit 1; the operator
     returns to refine to make the call manually.

Authoring command — coordination-only compatible overlap (independent):

```bash
yoke shepherd dependency-add \
    YOK-{candidate} YOK-{conflicting-item} refine \
    --gate-point coordination_only \
    --rationale "<non-empty: shared paths + disjoint subsections evidence>"
```

Authoring command — directional activation (order-dependent overlap):

```bash
yoke shepherd dependency-add \
    YOK-{candidate} YOK-{upstream} refine \
    --gate-point activation \
    --satisfaction fact:merged \
    --rationale "decision=directional. <why order matters: what upstream lands that this candidate inherits>"
```

After authoring, re-run ``yoke readiness check`` to confirm the
readiness repair landed.

## Refine entry recipe

```bash
_readiness_json=$(yoke readiness check "$ITEM_NUM" 2>/dev/null) || true
_class=$(printf '%s' "$_readiness_json" | python3 -c "
import json, sys
data = json.loads(sys.stdin.read() or '{}')
print(data.get('classification', 'unrecoverable'))
")
case "$_class" in
  pass)
    : # readiness clean; continue refine
    ;;
  pure_stale_count)
    _repair_json=$(yoke readiness repair-stale-count --item "$ITEM_NUM" 2>&1)
    _repair_rc=$?
    if [ "$_repair_rc" -ne 0 ]; then
      printf '%s\n' "$_repair_json"
      yoke sessions checkpoint --step 1 --action refine --chainable false --outcome blocked --item-id "YOK-$ITEM_NUM"
      yoke claims work release \
        --item "YOK-$ITEM_NUM" --reason "readiness-check-blocked" \
        >/dev/null 2>&1 || true
      exit 1
    fi
    # Repair succeeded — keep the claim, continue refine.
    ;;
  mixed_stale_count)
    yoke readiness repair-claim-coverage \
      --item "$ITEM_NUM" || {
      # Helper refused (mixed widen+narrow, zero/multiple exclusive claims,
      # or non-recoverable code mixed in). Continue into refine for repair;
      # step 4b's path-claim re-check + step 5/6 critique cover the
      # remaining work; the final readiness rerun catches any drift.
      printf 'Recoverable readiness gaps not auto-repaired; continuing into refine:\n%s\n' "$_readiness_json"
    }
    ;;
  unrecoverable)
    printf '%s\n' "$_readiness_json"
    yoke sessions checkpoint --step 1 --action refine --chainable false --outcome blocked --item-id "YOK-$ITEM_NUM"
    yoke claims work release \
      --item "YOK-$ITEM_NUM" --reason "readiness-check-blocked" \
      >/dev/null 2>&1 || true
    exit 1
    ;;
esac
```

The auto-widen branch for pure `FILE_BUDGET_NOT_IN_CLAIM` (and the
symmetric narrow path for pure `CLAIM_NOT_IN_FILE_BUDGET`) is now owned
by the Python helper
`yoke readiness repair-claim-coverage`. Refine dispatches to it from
`SKILL.md` step 1b's `mixed_stale_count` branch.
The helper applies the matching amendment via the existing
`path_claims_amend.widen` / `narrow` domain functions, re-runs
`yoke readiness check`, and emits
`IdeaReadinessClaimCoverageRepairApplied` for telemetry. Refusals
(mixed widen+narrow, zero or multiple non-terminal exclusive claims,
non-recoverable codes mixed in) surface structured `refused_paths`
entries and fall through into the rest of refine.

## /yoke do contract

A successful refine-entry stale-count repair is **continuation of the
same routed handler**, not a new chain step:

- The work claim stays held by the refine session — there is no
  release-and-re-claim choreography for repair-only.
- ``/yoke do``'s scheduler does not see a released claim, so it
  does not re-offer with a different item between the repair and the
  rest of refine.
- The chain step counter does not bump just because the repair
  happened. The handler ``completed`` outcome (or its eventual
  replacement) is recorded once when refine finishes the whole
  ``idea -> refining-idea -> refined-idea`` arc.

If the repair refuses (sibling-plan gap, ambiguous match, structured
write refusal), refine releases the claim with reason
`readiness-check-blocked` and exits 1. ``/yoke do`` records that
exit through the existing handler-outcome path; the chain step then
honors the operator's expected behavior (no special-case wiring is
required because the helper failure resolves to the same shape as
the prior unrecoverable branch).

## What the helper deliberately does NOT do

- It does **not** add or remove File Budget paths. The drift it
  repairs is purely numeric; structural changes to the budget are a
  spec decision, not metadata maintenance.
- It does **not** widen or narrow path claims. Claim mismatches flow
  through `SKILL.md` step 4b's path-claim re-check
  (`FILE_BUDGET_NOT_IN_CLAIM` / `CLAIM_NOT_IN_FILE_BUDGET`).
- It does **not** rewrite unrelated spec prose. Every other refine
  improvement happens in step 5/6 critique, where the operator's
  judgement is in the loop.
- It does **not** auto-skip the readiness gate. A `MISSING_SIBLING_PLAN`
  result — including one that emerges *after* repair when the new
  count crosses the threshold — still blocks the handler.
- It does **not** author directional `activation` edges. Those reflect a
  real serial ordering and should be authored manually via `/yoke
  refine` (see the `## Cross-item overlap repair` section above) or via
  `/yoke idea`'s path-claim reconciliation step
  ([path-claim-blocking.md](../idea/path-claim-blocking.md) section 3).

## Verification

```bash
python3 -m yoke_core.tools.watch_pytest -- runtime/api/domain/test_idea_readiness_repair.py runtime/api/test_skill_doc_regressions_file_budget.py
yoke readiness check {N}
yoke readiness repair-stale-count --item {N}
```

## When to use tentative path-claim coverage

When a File Budget entry names an exact path the operator believes is
**likely but not guaranteed** to be touched (a fixture schema mirror
that may be unnecessary if a sibling refactor extracts the canonical
form first; a re-export shim whose creation depends on a renaming
decision deferred to implementation; a doctrine-comment update that
might be redundant once an upstream documentation pass lands), declare
the path as **tentative** rather than planned.

Tentative coverage participates in overlap detection and renders
distinctly in the rendered ``## Path Claims`` section. Untouched
tentative paths release with the claim without flagging a missed
promise — there was never a promise. Tentative is *not* a substitute
for broad parent-directory coverage; it is exact-path coverage with a
weaker reservation.

Operator surface for refine: include the path in the spec's File
Budget AND in the path-claim's ``--paths`` list, and additionally
pass ``--tentative-paths`` for the subset that should mint as
``materialization_state='tentative'``. Path targets already at
``planned`` or ``observed`` are not downgraded — tentative declarations
on top of stronger existing state are no-ops. To upgrade tentative to
planned, amend the claim through the same ``--paths`` flow without
``--tentative-paths`` after a fresh ``register-claim`` (the runtime's
sticky-tentative rule prevents implicit upgrades through automatic
re-resolution; see
[packages/yoke-core/src/yoke_core/domain/path_targets_planning.py](../../../../packages/yoke-core/src/yoke_core/domain/path_targets_planning.py)).

## Symlink-aware repair advisory

When a File Budget entry resolves to an in-repo symlink on disk, the
readiness-repair check surfaces a one-line authoring hint and continues
without blocking:

> ``<symlink>`` is a symlink to ``<canonical>``; Yoke will claim both —
> list ``<canonical>`` in the File Budget so the human-readable surface
> matches.

Registration-time canonicalization (in
``yoke_core.domain.path_claims_resolve.expand_symlinks_to_canonical``)
auto-pairs the symlink-name with its canonical target_id, so the
overlap classifier sees the equivalence class regardless of which name
the operator authored. The hint nudges the next refinement pass toward
listing the canonical name in the File Budget; the underlying claim
already covers both target_ids either way.
